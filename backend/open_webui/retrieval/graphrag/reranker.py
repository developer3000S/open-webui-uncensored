"""Local cross-encoder reranker (rec 2.1).

The hybrid pipeline already uses the deployment's rerank endpoint when one is
configured (`RERANKING_FUNCTION`). This module fills the gap for deployments
*without* an external reranker: an optional local cross-encoder model scores
merged native/hybrid candidates so precision@k improves without any network
dependency.

Activation is strictly opt-in to keep cold starts and memory in check:
    ORCH_CE_RERANK=true                 enable
    ORCH_CE_MODEL=cross-encoder/ms-marco-MiniLM-L6-v2   model id
    ORCH_CE_MAX_DOCS=30                 scoring cap per query

Design notes (§15.1 budgets):
- Model load happens once, lazily, inside a thread — never on import;
- scoring runs via asyncio.to_thread so the event loop stays responsive;
- any failure (missing package, OOM, timeout) returns the input order —
  reranking is an upgrade path, not a dependency (fail-open to baseline).
"""

from __future__ import annotations

import asyncio
import logging
import os

log = logging.getLogger(__name__)

_model = None
_model_failed = False


def _enabled() -> bool:
    return os.getenv('ORCH_CE_RERANK', '').strip().lower() in ('1', 'true', 'yes', 'on')


def _model_id() -> str:
    return os.getenv('ORCH_CE_MODEL', 'cross-encoder/ms-marco-MiniLM-L6-v2').strip()


def _max_docs() -> int:
    try:
        return max(4, int(os.getenv('ORCH_CE_MAX_DOCS', '30')))
    except ValueError:
        return 30


def _load_model():
    """Import + instantiate lazily; cache failures so we don't retry per query."""
    global _model, _model_failed
    if _model is not None or _model_failed:
        return _model
    try:
        from sentence_transformers import CrossEncoder  # optional heavy dep

        _model = CrossEncoder(_model_id())
        log.info('orchestrator: cross-encoder loaded (%s)', _model_id())
    except Exception as e:
        _model_failed = True
        log.warning('orchestrator: cross-encoder unavailable (%s); rerank disabled', e)
    return _model


def _score_sync(query: str, docs: list[str]) -> list[float]:
    model = _load_model()
    if model is None:
        return []
    pairs = [(query, d[:2000]) for d in docs]
    return [float(s) for s in model.predict(pairs)]


async def rerank_documents(
    query: str,
    docs: list[str],
    metas: list[dict],
    top_n: int | None = None,
) -> tuple[list[str], list[dict]]:
    """Rescore (docs, metas) with the CE model; no-op unless enabled/available.

    Returns reordered (docs, metas) truncated to `top_n`. On any problem the
    original lists are returned untouched — callers must not special-case it.
    """
    if not _enabled() or not query or not docs:
        return docs, metas
    cap = min(len(docs), _max_docs())
    try:
        scores = await asyncio.to_thread(_score_sync, query, docs[:cap])
    except Exception as e:  # thread/to_thread guard; model errors cached inside
        log.debug('orchestrator: CE rerank skipped (%s)', e)
        return docs, metas
    if not scores or len(scores) != cap:
        return docs, metas
    tail_docs, tail_metas = docs[cap:], metas[cap:]
    order = sorted(range(cap), key=lambda i: scores[i], reverse=True)
    out_docs = [docs[i] for i in order] + tail_docs
    out_metas = [metas[i] for i in order] + tail_metas
    if top_n:
        out_docs, out_metas = out_docs[:top_n], out_metas[:top_n]
    return out_docs, out_metas
