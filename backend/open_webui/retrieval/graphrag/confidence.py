"""Confidence Estimation (ТЗ §4.2.4): how much processing does this need?

The estimate is a weighted blend of the signals the ТЗ enumerates — query
understanding quality, historical stats for similar requests, source
availability, data freshness and coverage — mapped onto the six processing
modes (§4.2.1). Calibration hook: `record_outcome` feeds realized answer
quality back per intent class so declared confidence tracks actual quality
(§4.2.4 п.5); the blended score is shrunk toward the class mean as evidence
accumulates.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time

from open_webui.retrieval.graphrag.models import ConfidenceEstimate
from open_webui.retrieval.graphrag.settings import OrchestratorSettings

log = logging.getLogger(__name__)

# Latency priors per pipeline, ms (matches the §5.1.1 targets table).
PIPELINE_LATENCY_MS = {
    'native_rag': 1500,
    'hybrid_rag': 2500,
    'graph_rag': 3000,
    'agentic_rag': 5000,
    'tool_pipeline': 4000,
}

_COST_UNITS = {
    'native_rag': 0.05,
    'hybrid_rag': 0.12,
    'graph_rag': 0.15,
    'agentic_rag': 0.6,
    'tool_pipeline': 0.2,
}

_HISTORY_PATH = os.getenv(
    'ORCH_CALIBRATION_PATH',
    os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), 'internal', 'orch_calibration.json'),
)

_history_lock = threading.Lock()
_history_cache: dict | None = None


def _load_history() -> dict:
    """{intent: {"n": int, "mean_quality": float}} persisted across restarts."""
    global _history_cache
    if _history_cache is not None:
        return _history_cache
    try:
        with open(_HISTORY_PATH) as f:
            _history_cache = json.load(f)
    except Exception:
        _history_cache = {}
    return _history_cache


def record_outcome(intent: str, quality: float) -> None:
    """Feed an observed evaluation score back for calibration (§4.2.4 п.5)."""
    quality = max(0.0, min(1.0, float(quality)))
    with _history_lock:
        history = _load_history()
        entry = history.setdefault(intent, {'n': 0, 'mean_quality': 0.6})
        n = entry['n'] + 1
        entry['mean_quality'] = entry['mean_quality'] + (quality - entry['mean_quality']) / n
        entry['n'] = n
        entry['updated_at'] = time.time()
        try:
            os.makedirs(os.path.dirname(_HISTORY_PATH), exist_ok=True)
            tmp = _HISTORY_PATH + '.tmp'
            with open(tmp, 'w') as f:
                json.dump(history, f)
            os.replace(tmp, _HISTORY_PATH)
        except Exception as e:
            log.debug('orchestrator calibration persist failed: %s', e)


def historical_mean(intent: str) -> tuple[float | None, int]:
    entry = _load_history().get(intent)
    if not entry:
        return None, 0
    return float(entry.get('mean_quality', 0.6)), int(entry.get('n', 0))


def estimate_confidence(
    analysis,
    policy,
    settings: OrchestratorSettings,
    *,
    sources_available: bool = True,
    index_fresh: bool = True,
    previous_attempts: int = 0,
) -> ConfidenceEstimate:
    """Score routing confidence and pick the processing mode (§4.2.4 п.3)."""
    reasons: list[str] = []

    # 1. Query understanding quality: dominant intent confidence vs ambiguity.
    confidences = sorted((analysis.intent_confidences or {}).values(), reverse=True)
    top_conf = confidences[0] if confidences else 0.5
    base = 0.35 + 0.35 * top_conf
    reasons.append(f'intent={analysis.intent} conf={top_conf:.2f}')

    # 2. Historical statistics for analogous requests (shrinks toward class mean).
    hist_mean, hist_n = historical_mean(analysis.intent)
    if hist_mean is not None and hist_n >= 5:
        weight = min(0.3, hist_n / 50.0)
        base = base * (1 - weight) + hist_mean * weight
        reasons.append(f'history[{analysis.intent}]={hist_mean:.2f} n={hist_n}')

    # 3. Source availability & 4. index quality/freshness (§7.6 актуальность).
    if not sources_available:
        base -= 0.35
        reasons.append('sources_unavailable')
    if not index_fresh:
        base -= 0.1
        reasons.append('index_stale')

    # 5. Coverage proxies from the analysis itself.
    base += 0.15 * float(analysis.answerability_score or 0.0)
    base -= 0.25 * float(analysis.ambiguity_score or 0.0)
    if analysis.requires_external_data and 'tool_pipeline' not in (policy.allowed_pipelines or []):
        base -= 0.2
        reasons.append('external_needed_but_disallowed')
    if analysis.requires_graph and 'graph_rag' not in (policy.allowed_pipelines or []):
        base -= 0.1
        reasons.append('graph_needed_but_disabled')

    # 6. Previous attempts: every failed escalation lowers expected success.
    if previous_attempts:
        base -= 0.12 * previous_attempts
        reasons.append(f'previous_attempts={previous_attempts}')

    routing_confidence = round(max(0.0, min(1.0, base)), 3)

    # Mode selection follows the §4.2.4 threshold table (configurable).
    unsafe = analysis.intent == 'unsafe' or 'critical' == getattr(policy, 'safety_level', 'low') and analysis.safety_risk_score >= 0.8
    if unsafe and analysis.safety_risk_score >= 0.9:
        mode = 'refusal_recommended'
        reasons.append('safety_risk_high')
    elif analysis.clarification_recommended or analysis.ambiguity_score >= 0.6:
        mode = 'clarification_required'
        reasons.append('ambiguous_query')
    elif routing_confidence >= settings.conf_single:
        mode = 'fast_path' if analysis.complexity == 'low' and not analysis.requires_multi_step else 'standard'
    elif routing_confidence >= settings.conf_parallel:
        mode = 'standard'
    elif routing_confidence >= settings.conf_escalate:
        mode = 'deep'
    else:
        mode = 'ensemble'

    # Complexity floor: very_high queries never ride the fast path.
    if mode == 'fast_path' and analysis.complexity in ('high', 'very_high'):
        mode = 'standard'
        reasons.append('complexity_floor')

    # Latency/cost estimates for the chosen ladder (§5.1.3 budgets).
    ladder = _mode_ladder(mode, analysis)
    est_latency = sum(PIPELINE_LATENCY_MS.get(p, 1500) for p in ladder)
    est_cost = sum(_COST_UNITS.get(p, 0.05) for p in ladder)

    return ConfidenceEstimate(
        routing_confidence=routing_confidence,
        estimated_success_probability=routing_confidence,
        estimated_latency_ms=min(est_latency, policy.max_latency_ms or est_latency),
        estimated_cost_units=round(min(est_cost, policy.max_cost_units or est_cost), 3),
        recommended_mode=mode,
        reason_codes=reasons,
    )


def _mode_ladder(mode: str, analysis) -> list[str]:
    """Pipelines a mode implies, for budget estimation only."""
    if mode in ('fast_path', 'standard'):
        return ['native_rag'] + (['graph_rag'] if analysis.requires_graph else [])
    if mode == 'deep':
        return ['native_rag', 'hybrid_rag']
    if mode == 'ensemble':
        return ['native_rag', 'hybrid_rag', 'graph_rag']
    return ['native_rag']
