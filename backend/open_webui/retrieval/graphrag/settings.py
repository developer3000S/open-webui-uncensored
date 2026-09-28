"""Runtime configuration of the adaptive RAG orchestrator (ТЗ §13.2, §13.3).

Knobs live in the persistent Config store under `rag.orchestrator.*` so an
admin can retune routing without a restart; every key falls back to an .env
default declared below, and those fall back to the literals here. The env keys
use the existing GRAPHRAG_* namespace where semantics match, plus ORCH_* for
the new orchestration layer.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field, asdict

log = logging.getLogger(__name__)

CONFIG_PREFIX = 'rag.orchestrator.'


def _env_flag(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in ('1', 'true', 'yes', 'on')


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, '') or default)
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, '') or default)
    except ValueError:
        return default


@dataclass
class OrchestratorSettings:
    """Feature flags + budgets + thresholds, one flat object (§13.3)."""

    # Master switch: when false the retrieval path behaves exactly like the
    # pre-orchestrator build (vector/hybrid search only).
    enabled: bool = field(default_factory=lambda: _env_flag('RAG_ORCHESTRATOR_ENABLED', True))
    # Per-pipeline toggles (§13.3 feature flags).
    graph_enabled: bool = field(default_factory=lambda: _env_flag('GRAPHRAG_ENABLED', False))
    hybrid_enabled: bool = field(default_factory=lambda: _env_flag('ORCH_HYBRID_ENABLED', True))
    agentic_enabled: bool = field(default_factory=lambda: _env_flag('ORCH_AGENTIC_ENABLED', False))
    web_tools_enabled: bool = field(default_factory=lambda: _env_flag('ORCH_WEB_TOOLS_ENABLED', False))
    ensemble_enabled: bool = field(default_factory=lambda: _env_flag('ORCH_ENSEMBLE_ENABLED', True))
    evaluation_enabled: bool = field(default_factory=lambda: _env_flag('ORCH_EVALUATION_ENABLED', True))
    citation_verification_enabled: bool = field(default_factory=lambda: _env_flag('ORCH_CITATION_VERIFICATION', True))
    safety_filter_enabled: bool = field(default_factory=lambda: _env_flag('ORCH_SAFETY_FILTER', True))
    cache_enabled: bool = field(default_factory=lambda: _env_flag('ORCH_CACHE_ENABLED', False))
    trace_store_enabled: bool = field(default_factory=lambda: _env_flag('ORCH_TRACE_STORE', True))

    # Routing mode inherited from the graph layer: auto | always | never.
    mode: str = field(default_factory=lambda: os.getenv('GRAPHRAG_MODE', 'auto').strip().lower())

    # Confidence thresholds — ТЗ §4.2.4 table, configurable per request.
    conf_single: float = field(default_factory=lambda: _env_float('ORCH_CONF_SINGLE', 0.85))
    conf_parallel: float = field(default_factory=lambda: _env_float('ORCH_CONF_PARALLEL', 0.65))
    conf_escalate: float = field(default_factory=lambda: _env_float('ORCH_CONF_ESCALATE', 0.45))

    # Budgets (§4.2.2 п.8). Zero means "unset → policy default".
    max_latency_ms: int = field(default_factory=lambda: _env_int('ORCH_MAX_LATENCY_MS', 30000))
    max_cost_units: float = field(default_factory=lambda: _env_float('ORCH_MAX_COST_UNITS', 1.0))
    max_agent_steps: int = field(default_factory=lambda: _env_int('ORCH_MAX_AGENT_STEPS', 6))
    max_tool_calls: int = field(default_factory=lambda: _env_int('ORCH_MAX_TOOL_CALLS', 8))
    max_candidates: int = field(default_factory=lambda: _env_int('ORCH_MAX_CANDIDATES', 4))

    # Per-pipeline timeouts used by the Execution Planner.
    native_timeout_ms: int = field(default_factory=lambda: _env_int('ORCH_NATIVE_TIMEOUT_MS', 20000))
    graph_timeout_ms: int = field(default_factory=lambda: _env_int('GRAPHRAG_QUERY_TIMEOUT', 20) * 1000)
    hybrid_timeout_ms: int = field(default_factory=lambda: _env_int('ORCH_HYBRID_TIMEOUT_MS', 25000))
    agentic_timeout_ms: int = field(default_factory=lambda: _env_int('ORCH_AGENTIC_TIMEOUT_MS', 60000))
    tool_timeout_ms: int = field(default_factory=lambda: _env_int('ORCH_TOOL_TIMEOUT_MS', 20000))

    # Evaluation thresholds (§10.2 escalation rules).
    min_overall_score: float = field(default_factory=lambda: _env_float('ORCH_MIN_OVERALL_SCORE', 0.45))
    min_groundedness: float = field(default_factory=lambda: _env_float('ORCH_MIN_GROUNDEDNESS', 0.5))
    max_unsupported_claim_ratio: float = field(default_factory=lambda: _env_float('ORCH_MAX_UNSUPPORTED_RATIO', 0.2))

    # Graph knobs are shared with the legacy graph module (single source).
    top_entities: int = field(default_factory=lambda: _env_int('GRAPHRAG_TOP_ENTITIES', 6))
    depth: int = field(default_factory=lambda: _env_int('GRAPHRAG_TRAVERSAL_DEPTH', 2))
    neighbor_limit: int = field(default_factory=lambda: _env_int('GRAPHRAG_NEIGHBOR_LIMIT', 12))

    def to_dict(self) -> dict:
        return asdict(self)


async def get_settings() -> OrchestratorSettings:
    """Build settings from env defaults, overlaid with stored Config values.

    Mirrors how the rest of retrieval reads `rag.*` config: DB wins unless the
    variable is pinned in .env. Import of the app models stays lazy so this
    module remains unit-testable without a database.
    """
    settings = OrchestratorSettings()
    try:
        from open_webui.models.config import Config

        keys = [f'{CONFIG_PREFIX}{name}' for name in settings.to_dict()]
        values = await Config.get_many(*keys)
        for name in settings.to_dict():
            stored = values.get(f'{CONFIG_PREFIX}{name}')
            if stored is not None:
                setattr(settings, name, stored)
    except Exception as e:  # no DB in unit tests / early boot — env defaults stand
        log.debug('orchestrator settings: using env defaults (%s)', e)
    return settings


def pipeline_timeout(settings: OrchestratorSettings, pipeline: str) -> int:
    return {
        'native_rag': settings.native_timeout_ms,
        'graph_rag': settings.graph_timeout_ms,
        'hybrid_rag': settings.hybrid_timeout_ms,
        'agentic_rag': settings.agentic_timeout_ms,
        'tool_pipeline': settings.tool_timeout_ms,
    }.get(pipeline, settings.native_timeout_ms)
