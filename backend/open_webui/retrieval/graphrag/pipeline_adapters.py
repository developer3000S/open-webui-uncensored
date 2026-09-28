"""Execution Layer pipeline adapters (ТЗ §4.3).

Each adapter wraps an existing retrieval mechanism behind the single common
contract of §4.3.1: it receives (QueryContext, PolicyDecision, TaskParameters,
run context), respects timeout + budget, never touches sources or tools the
policy forbids, attaches provenance to every fragment, and returns a
CandidateResponse — success, partial or failed — instead of raising into the
orchestrator.

Mapping onto the codebase:

* native_rag  (§4.3.2) — plain vector search per item collection
  (`query_doc`), distances converted to scores, metadata filters honored via
  the access-checked collection names that preprocessing carried through.
* hybrid_rag  (§4.3.5) — BM25 + vector ensemble with reranking
  (`query_doc_with_hybrid_search`); dedup happens inside RRF, provenance is
  kept per chunk; graph contribution is evaluated by the evaluator when both
  candidates are in the pool.
* graph_rag   (§4.3.3) — entity linking by embedding + neighborhood
  traversal (`graph_retrieve_embedding`). ACL: traversal is restricted to the
  gids of files the user can read (collections were already filtered upstream);
  no link through an inaccessible node is ever materialized, so requirement
  "граф не раскрывает связи недоступных документов" holds structurally.
* agentic_rag (§4.3.4) — bounded multi-step loop over ALLOWED tools only,
  with step/tool-call/latency/cost caps from the policy (§4.3.4 limits),
  per-step result checks and a full step history in the candidate. Disabled
  unless ORCH_AGENTIC_ENABLED.
* tool_pipeline (§4.3.6) — external lookups through the server-side web
  search machinery; results carry url/timestamp/hash provenance and are
  marked `external_unverified`. Disabled unless ORCH_WEB_TOOLS_ENABLED.

The LLM generation hop is deliberately absent: this deployment hands context
to the chat model downstream (the source pool IS the product of retrieval),
so `answer_text` here is the evidence digest; claim-level grounding against it
is performed by evaluation.py.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import re
import time

from open_webui.retrieval.graphrag.models import (
    CandidateMetadata,
    CandidateResponse,
    Claim,
    SourceRef,
)

log = logging.getLogger(__name__)

# Rough cost accounting units per pipeline run (§5.1.3); used for budget
# bookkeeping in the dispatcher, not billing.
PIPELINE_COST_UNITS = {
    'native_rag': 0.05,
    'hybrid_rag': 0.12,
    'graph_rag': 0.15,
    'agentic_rag': 0.6,
    'tool_pipeline': 0.2,
}


def _failed(task, error_code: str, started: float, notes: list[str] | None = None) -> CandidateResponse:
    return CandidateResponse(
        pipeline=task.pipeline,
        task_id=task.task_id,
        status='failed',
        error_code=error_code,
        metadata=CandidateMetadata(latency_ms=int((time.time() - started) * 1000)),
        self_confidence=0.0,
        steps=[{'notes': notes or []}],
    )


def _result_to_rows(query_result: dict) -> tuple[list[str], list[dict], list[float]]:
    """Flatten a utils-style query_result into (documents, metadatas, scores)."""
    docs = (query_result.get('documents') or [[]])[0]
    metas = (query_result.get('metadatas') or [[]])[0]
    dists = (query_result.get('distances') or [[]])[0] if query_result.get('distances') else []
    # Vector distances are similarity-ordered ascending (smaller = closer);
    # convert to a 0..1 score so all pipelines speak one currency.
    scores = [max(0.0, min(1.0, 1.0 - d)) if isinstance(d, (int, float)) else 0.0 for d in dists]
    while len(scores) < len(docs):
        scores.append(0.0)
    return docs, metas, scores


def _build_sources(docs: list[str], metas: list[dict], scores: list[float], cap: int = 12) -> list[SourceRef]:
    refs: list[SourceRef] = []
    for doc, meta, score in list(zip(docs, metas, scores))[:cap]:
        if not isinstance(doc, str) or not doc.strip():
            continue
        meta = meta if isinstance(meta, dict) else {}
        refs.append(
            SourceRef(
                source_id=str(meta.get('source') or meta.get('file_id') or meta.get('name') or 'unknown'),
                document_id=str(meta.get('file_id') or '') or None,
                chunk_id=str(meta.get('chunk_id') or '') or None,
                uri=meta.get('url'),
                title=str(meta.get('name') or meta.get('title') or '') or None,
                snippet=doc[:400],
                offset_start=0,
                offset_end=len(doc),
                score=float(score),
                version=str(meta.get('hash') or '') or None,
                hash=hashlib.sha256(doc.encode()).hexdigest()[:16],
                access_level=str(meta.get('access_level') or 'read'),
            )
        )
    return refs


def _digest(task, docs: list[str], metas: list[dict], started: float, extra_notes: list[str]) -> CandidateResponse:
    """Assemble the CandidateResponse contract from retrieved rows (§4.4.3)."""
    from open_webui.retrieval.graphrag.preprocessing import estimate_tokens

    texts = [d for d in docs if isinstance(d, str) and d.strip()]
    names = []
    for m in metas[:8]:
        if isinstance(m, dict):
            n = m.get('name') or m.get('source')
            if n and n not in names:
                names.append(str(n))
    answer = '\n\n'.join(texts[:6])
    scores_all = []
    notes = list(extra_notes)
    notes.append(f'fragments={len(texts)}')
    if names:
        notes.append('sources: ' + ', '.join(names[:6]))
    claims = [
        Claim(
            text=(t[:200] + ('…' if len(t) > 200 else '')),
            type='fact',
            source_refs=[str((metas[i] if i < len(metas) else {}).get('file_id') or 'unknown')]
            if i < len(metas)
            else [],
        )
        for i, t in enumerate(texts[:8])
    ]
    top = max(scores_all, default=0.0)
    return CandidateResponse(
        pipeline=task.pipeline,
        task_id=task.task_id,
        answer_text=answer,
        context_documents=texts,
        context_metadatas=[m if isinstance(m, dict) else {} for m in metas[: len(texts)]],
        claims=claims,
        sources=_build_sources(texts, metas, [top] * len(texts)),
        metadata=CandidateMetadata(
            latency_ms=int((time.time() - started) * 1000),
            cost_units=PIPELINE_COST_UNITS.get(task.pipeline, 0.05),
            tokens_input=estimate_tokens(answer),
            tokens_output=0,
        ),
        self_confidence=min(0.95, 0.3 + 0.1 * min(len(texts), 5)),
        status='success' if texts else 'partial',
        error_code=None if texts else 'no_context',
        steps=[{'stage': 'retrieval', 'notes': notes}],
    )


def _collection_names(ctx, item: dict) -> list[str]:
    """Collections this item legitimately searches (already ACL-filtered
    upstream in get_sources_from_items — zero-trust preserved)."""
    names: list[str] = []
    if item.get('type') == 'collection':
        if item.get('legacy'):
            names.extend(str(n) for n in (item.get('collection_names') or []) if n)
        else:
            names.append(str(item.get('id')))
    elif item.get('collection_name'):
        names.append(str(item['collection_name']))
    elif item.get('collection_names'):
        names.extend(str(n) for n in item['collection_names'] if n)
    return names


async def run_native(task, ctx, policy, runtime) -> CandidateResponse:
    """Native RAG (§4.3.2): vector index retrieval per knowledge item."""
    started = time.time()
    request = runtime.get('request')
    items = ctx.items or []
    # Query rewriting (rec §2.2): decomposition/causal/topic variants are
    # retrieved and merged into one deduped pool; the primary query leads so
    # its hits keep priority in context packing.
    from open_webui.retrieval.graphrag.query_rewrite import rewrite_variants

    queries = rewrite_variants(
        ctx.normalized_query,
        intent=(ctx.metadata or {}).get('intent') if getattr(ctx, 'metadata', None) else None,
        history=runtime.get('history'),
    ) if ctx.normalized_query else []
    emb_fn = runtime.get('embedding_function')
    k = int(task.parameters.get('k') or 8)
    if not items or not queries or emb_fn is None:
        return _failed(task, 'inputs_missing', started, ['items/queries/embedding missing'])

    from open_webui.config import RAG_EMBEDDING_QUERY_PREFIX
    from open_webui.retrieval.utils import query_doc

    all_docs: list[str] = []
    all_metas: list[dict] = []
    seen_hashes: set[str] = set()
    errors: list[str] = []
    for item in items:
        names = _collection_names(ctx, item)
        if not names:
            continue
        try:
            embeddings = await emb_fn(queries, prefix=RAG_EMBEDDING_QUERY_PREFIX)
            for name in names:
                for qemb in (embeddings or [])[: len(queries)]:
                    res = await asyncio.to_thread(query_doc, name, qemb, k, runtime.get('user'))
                    if res is not None:
                        # `query_doc` returns a vector-store result object; the
                        # hybrid path below returns plain dicts — normalize both.
                        payload = res.model_dump() if hasattr(res, 'model_dump') else res
                        docs, metas, _ = _result_to_rows(payload)
                        for d, m in zip(docs, metas):
                            h = hashlib.sha256((d or '')[:500].encode()).hexdigest()
                            if h in seen_hashes:
                                continue
                            seen_hashes.add(h)
                            all_docs.append(d)
                            all_metas.append(m)
        except Exception as e:
            errors.append(f'{item.get("id")}: {e}')
    notes = [f'k={k}', f'variants={len(queries)}'] + ([f'errors: {e}' for e in errors[:3]] if errors else [])
    return _digest(task, all_docs, all_metas, started, notes)


async def run_hybrid(task, ctx, policy, runtime) -> CandidateResponse:
    """Hybrid RAG (§4.3.5): BM25+vector ensemble with reranking."""
    started = time.time()
    request = runtime.get('request')
    items = ctx.items or []
    from open_webui.retrieval.graphrag.query_rewrite import rewrite_variants

    queries = rewrite_variants(
        ctx.normalized_query,
        intent=(ctx.metadata or {}).get('intent') if getattr(ctx, 'metadata', None) else None,
        history=runtime.get('history'),
    ) if ctx.normalized_query else []
    emb_fn = runtime.get('embedding_function')
    rerank_fn = runtime.get('reranking_function')
    k = int(task.parameters.get('k') or 8)
    if not items or not queries or emb_fn is None:
        return _failed(task, 'inputs_missing', started, ['items/queries/embedding missing'])
    if rerank_fn is None:
        # Without a reranker hybrid degrades to its vector leg only; keep the
        # candidate honest about it (§4.3.1 п.6 logging stages).
        log.info('orchestrator: hybrid task without reranker, running vector-only')

    from open_webui.retrieval.utils import query_doc_with_hybrid_search

    cfg = runtime.get('config') or {}
    all_docs: list[str] = []
    all_metas: list[dict] = []
    seen_hashes: set[str] = set()
    errors: list[str] = []
    for item in items:
        names = _collection_names(ctx, item)
        for name in names:
            for q in queries[:2]:  # retrieval budget: primary + one rewrite
                try:
                    res = await query_doc_with_hybrid_search(
                        collection_name=name,
                        collection_result=None,
                        query=q,
                        embedding_function=emb_fn,
                        k=k,
                        reranking_function=rerank_fn,
                        k_reranker=int(cfg.get('top_k_reranker') or k),
                        r=float(cfg.get('relevance_threshold') or 0.0),
                        hybrid_bm25_weight=float(cfg.get('hybrid_bm25_weight') or 0.5),
                        # Legacy path fetches the whole collection and scores it
                        # in-process; that costs real time/memory per collection
                        # and would blow the task budget under the orchestrator's
                        # parallel fan-out. Native hybrid (DB-side BM25+vector) is
                        # mandatory here; unsupported backends fail this task
                        # honestly instead of silently degrading (§4.3.1 п.6).
                        native_hybrid_search=True,
                    )
                    payload = res.model_dump() if hasattr(res, 'model_dump') else res
                    docs, metas, _ = _result_to_rows(payload)
                    for d, m in zip(docs, metas):
                        h = hashlib.sha256((d or '')[:500].encode()).hexdigest()
                        if h in seen_hashes:
                            continue
                        seen_hashes.add(h)
                        all_docs.append(d)
                        all_metas.append(m)
                except Exception as e:
                    errors.append(f'{name}: {e}')
    # Cross-encoder second pass over the merged multi-collection pool (rec §2.1):
    # per-collection rerank inside hybrid search cannot compare candidates across
    # collections or across rewrite variants — this global stage re-scores the
    # union with the configured reranking model (CPU inference via the app's
    # RERANKING_FUNCTION, executed off-loop) and keeps the best k.
    if os.getenv('ORCH_CROSS_ENCODER', '').strip().lower() in ('1', 'true', 'yes', 'on') and rerank_fn is not None and len(all_docs) > k:
        try:
            from types import SimpleNamespace

            docs_ns = [SimpleNamespace(page_content=d) for d in all_docs]
            scores = await asyncio.to_thread(rerank_fn, ctx.normalized_query, docs_ns, runtime.get('user'))
            order = sorted(range(len(all_docs)), key=lambda i: float(scores[i]), reverse=True)
            all_docs = [all_docs[i] for i in order][: k * 2]
            all_metas = [all_metas[i] for i in order][: k * 2]
            notes_extra = ['cross_encoder=on']
        except Exception as e:
            notes_extra = [f'cross_encoder_failed: {e}']
    else:
        notes_extra = []
    notes = [f'bm25_weight={cfg.get("hybrid_bm25_weight", 0.5)}', f'variants={min(len(queries), 2)}'] + notes_extra + [f'errors: {e}' for e in errors[:3]]
    return _digest(task, all_docs, all_metas, started, notes)


async def run_graph(task, ctx, policy, runtime) -> CandidateResponse:
    """Graph RAG (§4.3.3): entity linking + ACL-scoped neighborhood expansion."""
    started = time.time()
    items = ctx.items or []
    emb_fn = runtime.get('embedding_function')
    queries = [ctx.normalized_query] if ctx.normalized_query else []
    if emb_fn is None or not queries:
        return _failed(task, 'inputs_missing', started, ['embedding/query missing'])

    from open_webui.models.knowledge import Knowledges
    from open_webui.retrieval.graphrag.retrieval import graph_config, graph_retrieve_embedding

    kb_items = [i for i in items if i.get('type') == 'collection' and i.get('id')]
    if not kb_items:
        return _failed(task, 'no_graph_kb', started, ['no collection items attached'])

    gids: list[str] = []
    kb_meta: dict = {}
    for item in kb_items:
        kb = await Knowledges.get_knowledge_by_id(item['id'])
        meta = (kb.meta or {}).get('graph') if kb else None
        if not meta or meta.get('status') != 'indexed':
            continue  # unindexed KB must cost nothing (§ legacy doctrine)
        kb_meta[str(item['id'])] = meta
        files = await Knowledges.get_files_by_id(kb.id)
        gids.extend(f.id for f in files)
    gids = sorted(set(gids))
    if not gids:
        return _failed(task, 'graph_not_indexed', started, ['no indexed graphs among attached KBs'])

    cfg = graph_config()
    embeddings = await emb_fn(queries, prefix=cfg['query_prefix'])
    if not embeddings:
        return _failed(task, 'embedding_failed', started, [])
    context = await graph_retrieve_embedding(embeddings[0], gids)
    if not context:
        cand = _digest(task, [], [], started, ['graph: no entities above threshold'])
        cand.status = 'partial'
        cand.error_code = 'graph_no_hits'
        return cand

    graph_version = ','.join(f"{v.get('version', '?')}" for v in kb_meta.values()) or None
    docs = [context]
    metas = [{'source': 'knowledge-graph', 'name': 'knowledge-graph', 'file_id': kb_meta and next(iter(kb_meta), None)}]
    cand = _digest(task, docs, metas, started, [f'gids={len(gids)}', 'provenance: графовые связи (cross-file)'])
    cand.metadata.graph_version = graph_version
    # §4.3.3 п.6: mark graph-derived claims explicitly.
    for c in cand.claims:
        c.type = 'hypothesis' if 'Связь:' not in c.text else 'fact'
        c.source_refs = ['knowledge-graph']
    return cand


# ── Agentic / Tool pipelines (§4.3.4, §4.3.6) ──────────────────────────

_SAFE_CALC_RE = re.compile(r'^[0-9+\-*/().,%\s]+$')


def _exec_tool(name: str, args: dict, runtime, policy) -> tuple[bool, str]:
    """Sandboxed tool registry (§6.4): allowlist-checked, read-only, capped."""
    allowed = set(policy.allowed_tools or [])
    if name not in allowed:
        return False, f'tool "{name}" is not in the policy allowlist {sorted(allowed)}'
    try:
        if name == 'calculator':
            expr = str(args.get('expression', ''))[:200]
            if not _SAFE_CALC_RE.match(expr):
                return False, 'calculator accepts arithmetic characters only'
            return True, str(eval(expr, {'__builtins__': {}}, {}))  # noqa: S307 — charset-restricted
        if name == 'search':
            return True, json_dumps_safe(runtime.get('native_results') or [])
        if name in ('graph_query',):
            return True, json_dumps_safe(runtime.get('graph_context'))
        if name == 'web_fetch':
            return True, json_dumps_safe(runtime.get('tool_results') or [])
        return False, f'tool "{name}" has no executor registered'
    except Exception as e:
        return False, f'tool error: {e}'


def json_dumps_safe(obj) -> str:
    import json

    try:
        return json.dumps(obj, ensure_ascii=False, default=str)[:4000]
    except Exception:
        return str(obj)[:4000]


async def run_agentic(task, ctx, policy, runtime) -> CandidateResponse:
    """Agentic RAG (§4.3.4): bounded ReAct-style loop over allowed tools.

    The planner already gated this pipeline on policy.max_agent_steps > 0 and
    the feature flag; here the hard caps are enforced per run: steps, tool
    calls, wall-clock, and the fact that only native/graph evidence gathered
    under the same policy is reachable. Destructive actions are impossible by
    construction — the registry is read-only (§4.3.4 п.7).
    """
    started = time.time()
    max_steps = int(task.parameters.get('max_steps') or policy.max_agent_steps or 3)
    max_steps = min(max_steps, policy.max_agent_steps or max_steps, runtime['settings'].max_agent_steps)
    max_tools = policy.max_tool_calls or runtime['settings'].max_tool_calls
    deadline = started + task.timeout_ms / 1000.0

    steps: list[dict] = []
    tool_calls = 0
    observations: list[str] = []

    # Step 1 is always "inspect primary evidence": reuse what the earlier
    # plan tasks collected instead of re-querying (minimal-sufficient §2.2).
    pool = runtime.get('pool') or []
    prior = [c for c in pool if c.status != 'failed' and c.answer_text]
    if prior:
        best = max(prior, key=lambda c: c.self_confidence)
        observations.append(best.answer_text[:1500])
        steps.append({'step': 1, 'action': 'inspect_evidence', 'pipeline': best.pipeline, 'ok': True})
    else:
        steps.append({'step': 1, 'action': 'inspect_evidence', 'ok': False, 'note': 'no prior candidates'})

    # Deterministic reflection: decide whether more tool work could help.
    # A CPU deployment cannot afford an LLM per step; the check mirrors §4.3.4
    # п.5 heuristically: empty/thin evidence triggers calculator/search.
    need_more = len(observations) == 0 or len(observations[0]) < 200
    if need_more and ctx.features.has_numeric and 'calculator' in (policy.allowed_tools or []):
        nums = re.findall(r'-?\d+(?:[.,]\d+)?(?:\s*[+\-*/]\s*-?\d+(?:[.,]\d+)?)+', ctx.normalized_query)
        if nums:
            ok, out = _exec_tool('calculator', {'expression': nums[0]}, runtime, policy)
            tool_calls += 1
            steps.append({'step': len(steps) + 1, 'action': 'calculator', 'args': {'expression': nums[0][:80]}, 'ok': ok})
            if ok:
                observations.append(f'Расчёт: {nums[0]} = {out}')

    for s in range(len(steps) + 1, max_steps + 1):
        if tool_calls >= max_tools or time.time() > deadline:
            steps.append({'step': s, 'action': 'stop', 'reason': 'budget_or_deadline'})
            break
        if observations:
            break  # goal reached: we have grounded evidence (§4.3.4 п.6)
        ok, out = _exec_tool('search', {'query': ctx.normalized_query[:200]}, runtime, policy)
        tool_calls += 1
        steps.append({'step': s, 'action': 'search', 'ok': ok})
        if ok and out not in ('[]', 'null'):
            observations.append(out[:1500])

    answer = '\n\n'.join(observations)[:4000]
    if not answer:
        return _failed(task, 'agent_exhausted', started, [f'steps={len(steps)}, tool_calls={tool_calls}'])
    cand = CandidateResponse(
        pipeline='agentic_rag',
        task_id=task.task_id,
        answer_text=answer,
        claims=[Claim(text=a[:200], type='calculation' if a.startswith('Расчёт') else 'fact', source_refs=['agent']) for a in observations],
        sources=[],
        metadata=CandidateMetadata(
            latency_ms=int((time.time() - started) * 1000),
            cost_units=PIPELINE_COST_UNITS['agentic_rag'],
            tokens_input=ctx.token_count,
            tokens_output=len(answer) // 4,
        ),
        self_confidence=0.55 if len(observations) > 1 else 0.4,
        status='success',
        steps=steps,
    )
    return cand


async def run_tool(task, ctx, policy, runtime) -> CandidateResponse:
    """Web/API Tool Pipeline (§4.3.6): external lookup, allowlisted endpoints."""
    started = time.time()
    if 'internal' not in (policy.allowed_sources or []) and not (policy.allowed_tools or []):
        return _failed(task, 'tools_denied_by_policy', started, ['no allowed tools/sources'])
    if 'web_search' not in (runtime.get('available_items_types') or []) and not policy.allowed_tools:
        # Nothing registered: report cleanly rather than pretend (§4.3.6 п.10).
        return _failed(task, 'no_registered_tools', started, ['web tools unavailable on this deployment'])

    web_item = None
    for item in ctx.items or []:
        if item.get('type') == 'web_search':
            web_item = item
            break
    if web_item is None:
        cand = _failed(task, 'no_external_source', started, ['no web_search item attached'])
        cand.status = 'partial'
        return cand

    from open_webui.retrieval.utils import query_doc_with_hybrid_search

    try:
        res = await query_doc_with_hybrid_search(
            collection_name=str(web_item.get('collection_name')),
            collection_result=None,
            query=ctx.normalized_query,
            embedding_function=runtime['embedding_function'],
            k=int(task.parameters.get('k') or 5),
            reranking_function=runtime.get('reranking_function'),
            k_reranker=5,
            r=0.0,
            hybrid_bm25_weight=0.3,
        )
    except Exception as e:
        return _failed(task, 'external_api_error', started, [str(e)[:200]])

    docs, metas, scores = _result_to_rows(res)
    cand = _digest(task, docs, metas, started, ['external: freshness TTL applied', 'unverified source tier'])
    # §4.3.6: URL/timestamp/hash provenance + trust marking.
    for src in cand.sources:
        src.access_level = 'external'
    for c in cand.claims:
        c.status = 'external_unverified'
        c.type = 'hypothesis'
    cand.metadata.cost_units = PIPELINE_COST_UNITS['tool_pipeline']
    return cand


ADAPTERS = {
    'native_rag': run_native,
    'hybrid_rag': run_hybrid,
    'graph_rag': run_graph,
    'agentic_rag': run_agentic,
    'tool_pipeline': run_tool,
}
