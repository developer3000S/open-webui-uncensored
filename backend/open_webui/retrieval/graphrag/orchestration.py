"""Adaptive RAG orchestrator — the §10.4 control loop, wired end to end.

`orchestrate_retrieval` is the query-path entry point: Preprocessing → cache
→ Policy → Query Understanding → Confidence → Planning → Execution (+one
bounded escalation rung) → Evaluation → Synthesis → TraceRecord. It returns
the legacy-shaped `sources` list on success (so every downstream consumer —
citation panel, streaming events, models.py context builder — keeps working
unchanged), or None when it cannot produce anything better than the baseline
vector/hybrid path, in which case `get_sources_from_items` proceeds exactly as
before. Fail-closed doctrine (§5.2): any internal failure degrades to the
baseline, never to a broken chat request.

The graph augmentation of the baseline path (`maybe_augment_with_graph`) stays
untouched: it remains the answer when the orchestrator is off or abstains.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time

from open_webui.retrieval.graphrag import trace_store
from open_webui.retrieval.graphrag.confidence import estimate_confidence, record_outcome
from open_webui.retrieval.graphrag.context_manager import pack_context
from open_webui.retrieval.graphrag.execution import execute_plan, insufficient
from open_webui.retrieval.graphrag.models import TraceRecord, Usage, new_id, now_iso
from open_webui.retrieval.graphrag.planner import build_plan, escalate_plan
from open_webui.retrieval.graphrag.policy import POLICY_CONFIG_KEY, evaluate_policy, load_policy_doc
from open_webui.retrieval.graphrag.preprocessing import preprocess_query
from open_webui.retrieval.graphrag.query_understanding import analyze_query
from open_webui.retrieval.graphrag.response_synthesizer import synthesize
from open_webui.retrieval.graphrag.evaluation import evaluate_candidates
from open_webui.retrieval.graphrag.settings import OrchestratorSettings, get_settings

log = logging.getLogger(__name__)

ORCHESTRATOR_VERSION = '1.0.0'

# In-process response cache (§4.1.2 п.10, §7.5): tiny LRU with TTL — this
# deployment is single-container; correctness over speed (cache disabled by
# default via ORCH_CACHE_ENABLED=false).
_cache: dict[str, tuple[float, dict]] = {}


def _cache_get(key: str):
    entry = _cache.get(key)
    if not entry:
        return None
    expires, value = entry
    if time.time() > expires:
        _cache.pop(key, None)
        return None
    return value


def _cache_put(key: str, value: dict, ttl_s: int) -> None:
    if len(_cache) > 128:
        for k in sorted(_cache, key=lambda k: _cache[k][0])[:32]:
            _cache.pop(k, None)
    _cache[key] = (time.time() + ttl_s, value)


def _sources_from_response(response: dict) -> list[dict]:
    """Project FinalResponse.sources_summary into the legacy sources shape."""
    sources: list[dict] = []
    for row in response.get('sources_summary') or []:
        docs = row.get('documents') or []
        metas = row.get('metadatas') or [{} for _ in docs]
        if docs:
            sources.append(
                {
                    'source': {'id': row.get('pipeline', 'orchestrated'),
                               'type': 'collection',
                               'name': f"оркестратор: {row.get('pipeline', '?')}"},
                    'document': docs,
                    'metadata': metas[: len(docs)],
                }
            )
    # Citations carry provenance metadata even when UI shows only links (§4.5.6).
    if response.get('citations'):
        for s in sources:
            s['citations'] = response['citations'][:10]
    return sources


async def orchestrate_retrieval(
    request,
    queries: list[str],
    items: list[dict],
    user,
    *,
    embedding_function,
    reranking_function=None,
    k: int = 5,
    full_context: bool = False,
    history: list[dict] | None = None,
    session_id: str | None = None,
    config: dict | None = None,
) -> list[dict] | None:
    """Run the full pipeline; None means "baseline path, proceed as before"."""
    settings: OrchestratorSettings = await get_settings()
    if not settings.enabled or not settings.graph_enabled and not settings.hybrid_enabled:
        return None
    if not items or not queries:
        return None
    query = max((q for q in queries if isinstance(q, str)), key=len, default='')
    if not query.strip():
        return None

    t0 = time.perf_counter()
    trace = TraceRecord(request_id=new_id(), tenant_id=getattr(user, 'tenant_id', None), user_id=getattr(user, 'id', None))

    try:
        ctx = preprocess_query(
            query,
            user={'id': getattr(user, 'id', ''), 'role': getattr(user, 'role', 'user'),
                  'tenant_id': getattr(user, 'tenant_id', None)},
            history=history,
            session_id=session_id,
            items=items,
        )
        trace.trace_id = ctx.trace_id
        trace.query_analysis = {}

        # Cache hit short-circuit (§10.4 pre-check).
        if settings.cache_enabled:
            hit = _cache_get(ctx.cache_key)
            if hit is not None:
                hit['ui_hints'] = {**(hit.get('ui_hints') or {}), 'cache_hit': True}
                trace.warnings.append('cache_hit')
                trace.total_latency_ms = int((time.perf_counter() - t0) * 1000)
                trace.final_response = hit
                if settings.trace_store_enabled:
                    trace.ended_at = now_iso()
                    asyncio.get_running_loop().run_in_executor(None, trace_store.store_trace, trace.model_dump())
                return _sources_from_response(hit)

        policy_doc = None
        try:
            from open_webui.models.config import Config

            policy_doc = await Config.get(POLICY_CONFIG_KEY)
        except Exception:
            pass
        policy = evaluate_policy(ctx, _noop_analysis(), settings, load_policy_doc(policy_doc))
        trace.policy_decision = policy.model_dump()

        if policy.deny:
            # Refusal without touching data (§4.2.2 п.10) — but retrieval here
            # must not silently drop attached content; abstain and let the
            # safety posture upstream handle prompt-level refusal instead.
            log.info('orchestrator: policy deny (%s), abstaining from orchestrated path', policy.deny_reason)
            return None

        analysis = analyze_query(ctx)
        trace.query_analysis = analysis.model_dump()

        confidence = estimate_confidence(analysis, policy, settings)
        plan = build_plan(analysis, policy, confidence, settings)
        trace.execution_plan = plan.model_dump()

        runtime = {
            'request': request,
            'user': user,
            'embedding_function': embedding_function,
            'reranking_function': reranking_function,
            'settings': settings,
            'config': config or {},
            'available_items_types': [i.get('type') for i in items if isinstance(i, dict)],
            'pool': [],
        }

        used_pipelines: list[str] = []
        all_runs: list[dict] = []

        if plan.tasks:
            pool, runs = await execute_plan(plan, ctx, policy, runtime, settings)
            all_runs.extend(runs)
            used_pipelines.extend(r['pipeline'] for r in runs if r['status'] != 'skipped')
            runtime['pool'] = pool

            # One bounded escalation rung (§10.4, §10.2). A second attempt is
            # paid for only when the first pool is genuinely insufficient and
            # budget remains.
            elapsed_ms = int((time.perf_counter() - t0) * 1000)
            if insufficient(pool, settings) and runtime['spent_latency_ms'] + 2000 < min(
                policy.max_latency_ms or settings.max_latency_ms, settings.max_latency_ms
            ):
                nxt = escalate_plan(plan, analysis, policy, settings)
                if nxt is not None and nxt.tasks:
                    trace.warnings.append(f'escalated: {nxt.rationale}')
                    pool2, runs2 = await execute_plan(nxt, ctx, policy, runtime, settings)
                    all_runs.extend(runs2)
                    used_pipelines.extend(r['pipeline'] for r in runs2 if r['status'] != 'skipped')
                    pool.extend(pool2)
                    runtime['pool'] = pool

        report = evaluate_candidates(list(runtime['pool']), ctx, analysis, policy, settings)
        if report.recommended_action == 'escalate' and policy.escalation_allowed and not insufficient(runtime['pool'], settings):
            # evaluator asked to escalate but pool already cleared the bar —
            # trust the numbers, downgrade to select (§10.3 деэскалация).
            report.recommended_action = 'select'

        usage = Usage(
            latency_ms=int((time.perf_counter() - t0) * 1000),
            cost_units=float(runtime.get('spent_cost_units', 0.0)),
            tokens_input=ctx.token_count,
            tokens_output=sum(c.metadata.tokens_output for c in runtime['pool']),
        )
        response = synthesize(ctx, list(runtime['pool']), report, policy, settings, used_pipelines, usage)

        # Context packing (§4.4.2): the delivered source documents are fitted
        # into the model's context budget before they reach the chat path.
        src_rows = _sources_from_response(response.model_dump())
        budget = int(os.getenv('ORCH_CONTEXT_TOKENS', '8000'))
        packed = []
        for row in src_rows:
            docs, metas = pack_context(row['document'], row['metadata'], token_budget=budget)
            packed.append({**row, 'document': docs, 'metadata': metas})
        src_rows = [p for p in packed if p['document']]

        trace.pipeline_runs = all_runs
        trace.candidates = [c.model_dump() for c in runtime['pool']]
        trace.evaluation_report = report.model_dump()
        trace.final_response = response.model_dump()
        trace.total_latency_ms = usage.latency_ms
        trace.total_cost_units = usage.cost_units
        trace.versions = {
            'orchestrator': ORCHESTRATOR_VERSION,
            'policy_version': policy.policy_version,
            'generation_models': [],
            'index_version': None,
            'graph_version': next((c.metadata.graph_version for c in runtime['pool'] if c.metadata.graph_version), None),
        }

        # Calibration feedback loop (§4.2.4 п.5): realized quality per intent.
        record_outcome(analysis.intent, report.confidence)

        if response.status in ('answered', 'partial', 'uncertain') and src_rows:
            if settings.cache_enabled and response.status == 'answered':
                _cache_put(ctx.cache_key, response.model_dump(), int(os.getenv('ORCH_CACHE_TTL_S', '300')))
            trace.ended_at = now_iso()
            if settings.trace_store_enabled:
                asyncio.get_running_loop().run_in_executor(None, trace_store.store_trace, trace.model_dump())
            log.info(
                'orchestrator: %s mode=%s pipelines=%s conf=%.2f latency=%dms',
                response.status, plan.mode, sorted(set(used_pipelines)) or ['-'], report.confidence, usage.latency_ms,
            )
            return src_rows

        # Unclear/refused-with-no-evidence: hand back to the baseline path so
        # the user still gets the standard vector answer (§10.2 fallback).
        trace.warnings.append(f'abstained: status={response.status}')
        trace.ended_at = now_iso()
        if settings.trace_store_enabled:
            asyncio.get_running_loop().run_in_executor(None, trace_store.store_trace, trace.model_dump())
        return None
    except Exception as e:
        log.warning('orchestrator: degrading to baseline path (%s)', e)
        trace.errors.append(str(e)[:300])
        trace.ended_at = now_iso()
        if settings.trace_store_enabled:
            try:
                asyncio.get_running_loop().run_in_executor(None, trace_store.store_trace, trace.model_dump())
            except Exception:
                pass
        return None


def _noop_analysis():
    """Minimal analysis stand-in for the pre-analysis policy pass (deny check
    needs only safety flags, which live on the context itself)."""

    class _A:
        safety_risk_score = 0.0
        domain = None

    return _A()
