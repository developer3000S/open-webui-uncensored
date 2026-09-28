"""Admin-facing service layer for the adaptive RAG orchestrator.

Thin, dependency-light helpers used by `routers/graphrag.py`: settings snapshot,
trace listing/detail, feedback intake (wired into confidence calibration),
drift metrics and policy document read/write. Everything is best-effort — an
observability failure must never surface as a chat-path failure (§5.2).
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from open_webui.retrieval.graphrag import trace_store
from open_webui.retrieval.graphrag.circuit_breaker import registry as cb_registry
from open_webui.retrieval.graphrag.confidence import record_outcome
from open_webui.retrieval.graphrag.models import FeedbackRecord
from open_webui.retrieval.graphrag.policy import DEFAULT_POLICY_DOC, POLICY_CONFIG_KEY, load_policy_doc
from open_webui.retrieval.graphrag.settings import CONFIG_PREFIX, get_settings

log = logging.getLogger(__name__)


async def status_snapshot() -> dict:
    """Effective orchestration state: env+DB settings, trace quality, cache."""
    settings = await get_settings()
    summary = {
        'enabled': settings.enabled,
        'mode': settings.mode,
        'pipelines': {
            'native_rag': True,
            'hybrid_rag': settings.hybrid_enabled,
            'graph_rag': settings.graph_enabled,
            'agentic_rag': settings.agentic_enabled,
            'tool_pipeline': settings.web_tools_enabled,
        },
        'thresholds': {
            'conf_single': settings.conf_single,
            'conf_parallel': settings.conf_parallel,
            'conf_escalate': settings.conf_escalate,
            'min_overall_score': settings.min_overall_score,
            'min_groundedness': settings.min_groundedness,
        },
        'budgets': {
            'max_latency_ms': settings.max_latency_ms,
            'max_cost_units': settings.max_cost_units,
            'max_agent_steps': settings.max_agent_steps,
            'max_tool_calls': settings.max_tool_calls,
        },
        'trace_store': settings.trace_store_enabled,
        'cache': settings.cache_enabled,
        'shadow_percent': settings.shadow_percent,
        'eval_llm': settings.eval_llm_enabled,
        # Dependency health (rec 3.2): closed/open/half_open per backend.
        'circuit_breakers': cb_registry.status(),
        'recent_quality': trace_store.recent_feedback_quality(24),
    }
    return summary


def list_traces(**filters) -> list[dict]:
    return trace_store.list_traces(**filters)


def get_trace(trace_id: str) -> dict | None:
    return trace_store.get_trace(trace_id)


async def submit_feedback(payload: dict) -> dict:
    """Persist feedback and feed it into confidence calibration (§4.7).

    rating: +1/-1 thumbs or 1..5 usefulness; normalized to 0..1 quality fed to
    `record_outcome(intent, quality)` so the per-intent historical mean tracks
    realized answer quality.
    """
    fb = FeedbackRecord(
        trace_id=str(payload.get('trace_id') or ''),
        response_id=payload.get('response_id'),
        rating=payload.get('rating'),
        kind=payload.get('kind', 'explicit'),
        signal=payload.get('signal'),
        comment=payload.get('comment'),
        created_at=datetime.now(timezone.utc).isoformat(),
    )
    trace_store.store_feedback(fb.model_dump())

    calibrated = False
    if fb.rating is not None and fb.trace_id:
        try:
            trace = trace_store.get_trace(fb.trace_id) or {}
            intent = (trace.get('query_analysis') or {}).get('intent') or 'unknown'
            r = float(fb.rating)
            # thumbs scale (-1..1) and 1..5 usefulness both normalize to 0..1
            quality = (r + 1) / 2 if abs(r) <= 1 else (r - 1) / 4
            record_outcome(intent, max(0.0, min(1.0, quality)))
            calibrated = True
        except Exception as e:  # calibration is opportunistic
            log.warning('feedback calibration skipped: %s', e)
    return {'feedback_id': fb.feedback_id, 'stored': True, 'calibrated': calibrated}


async def get_policy() -> dict:
    from open_webui.models.config import Config

    stored = await Config.get(POLICY_CONFIG_KEY)
    return load_policy_doc(stored if isinstance(stored, dict) else None)


async def put_policy(doc: dict) -> dict:
    """Validate-and-store a policy document overlay (policy-as-code, §4.2.2)."""
    from open_webui.models.config import Config

    if not isinstance(doc, dict):
        raise ValueError('policy document must be a JSON object')
    merged = load_policy_doc(doc)  # raises on malformed shapes via attribute access
    known_pipelines = set(DEFAULT_POLICY_DOC['default']['allowed_pipelines']) | set(
        ['native_rag', 'hybrid_rag', 'graph_rag', 'agentic_rag', 'tool_pipeline']
    )
    for scope in ['default', *(merged.get('roles') or {}), *(merged.get('tenants') or {})]:
        patch = (doc.get('default') if scope == 'default' else None) or _scope_patch(doc, scope)
        allowed = (patch or {}).get('allowed_pipelines')
        if allowed is not None:
            bad = [p for p in allowed if p not in known_pipelines]
            if bad:
                raise ValueError(f'unknown pipelines in scope {scope!r}: {bad}')
    await Config.set(POLICY_CONFIG_KEY, doc)
    return merged


def _scope_patch(doc: dict, scope: str) -> dict | None:
    if scope in (doc.get('roles') or {}):
        return doc['roles'][scope]
    if scope in (doc.get('tenants') or {}):
        return doc['tenants'][scope]
    return None


async def update_settings(partial: dict) -> dict:
    """Hot-retune orchestration knobs under `rag.orchestrator.<name>` keys."""
    from open_webui.models.config import Config

    settings = await get_settings()
    valid = set(settings.to_dict())
    applied, rejected = {}, []
    for key, value in (partial or {}).items():
        if key not in valid:
            rejected.append(key)
            continue
        current = getattr(settings, key)
        if isinstance(current, bool):
            value = bool(value)
        elif isinstance(current, int) and not isinstance(current, bool):
            value = int(value)
        elif isinstance(current, float):
            value = float(value)
        await Config.set(f'{CONFIG_PREFIX}{key}', value)
        applied[key] = value
    return {'applied': applied, 'rejected': rejected}


async def explain_trace(trace_id: str) -> dict | None:
    """Human-readable "why this answer" rendering of a trace (rec §4 UX).

    Projects the raw TraceRecord into the fields a UI panel needs: routing
    rationale from the plan, per-pipeline latency/cost, evaluation verdict and
    the list of used sources — without leaking other tenants' data (lookup is
    by unique trace_id; tenant check stays with the calling router)."""
    trace = trace_store.get_trace(trace_id)
    if not trace:
        return None
    plan = trace.get('execution_plan') or {}
    runs = trace.get('pipeline_runs') or []
    report = trace.get('evaluation_report') or {}
    response = trace.get('final_response') or {}
    return {
        'trace_id': trace.get('trace_id'),
        'status': response.get('status'),
        'confidence': response.get('confidence') or report.get('confidence'),
        'intent': (trace.get('query_analysis') or {}).get('intent'),
        'mode': plan.get('mode'),
        'rationale': plan.get('rationale'),
        'pipelines': [
            {
                'pipeline': r.get('pipeline'),
                'status': r.get('status'),
                'latency_ms': r.get('latency_ms'),
                'error_code': r.get('error_code'),
            }
            for r in runs
        ],
        'total_latency_ms': trace.get('total_latency_ms'),
        'total_cost_units': trace.get('total_cost_units'),
        'warnings': trace.get('warnings') or [],
        'citations': (response.get('citations') or [])[:10],
    }


def followup_suggestions(ctx_query: str, top_entities: list[str], limit: int = 3) -> list[str]:
    """Cheap deterministic follow-up questions from retrieved entities (rec §4).

    Full graph-neighbor suggestion generation would need an LLM hop; this gives
    the UI something useful immediately, and the endpoint can be upgraded to
    graph traversal later without changing its contract."""
    out: list[str] = []
    seen: set[str] = set()
    for e in top_entities or []:
        if len(out) >= limit:
            break
        e = str(e).strip()
        key = e.lower()
        if not e or key in seen or key in ctx_query.lower():
            continue
        seen.add(key)
        out.append(f'Подробнее про «{e}»?')
    return out
