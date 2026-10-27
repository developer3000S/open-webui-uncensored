"""Policy Engine (ТЗ §4.2.2): who may use what, at which budget.

Policies are data, not code (§4.2.2 recommended): a JSON document stored in
Config under `rag.orchestrator.policy` with layered overrides — global default,
per-role, per-tenant — merged in that order ("policy as code", versionable via
the stored doc's `version` field). The engine enforces zero-trust defaults:
anything not explicitly allowed is disallowed, and safety-critical requests
never escalate autonomy beyond the tenant's ceiling.
"""

from __future__ import annotations

import logging

from open_webui.retrieval.graphrag.models import PolicyDecision
from open_webui.retrieval.graphrag.settings import OrchestratorSettings

log = logging.getLogger(__name__)

POLICY_CONFIG_KEY = 'rag.orchestrator.policy'

ALL_PIPELINES = ['native_rag', 'hybrid_rag', 'graph_rag', 'agentic_rag', 'tool_pipeline']

# High-risk domains get ensemble + mandatory citations (§10.1 last row).
CRITICAL_DOMAINS = {'медицина', 'medical', 'право', 'legal', 'финансы', 'finance', 'security'}

DEFAULT_POLICY_DOC: dict = {
    'version': '1',
    'default': {
        'allowed_pipelines': ['native_rag', 'hybrid_rag'],
        'allowed_tools': [],
        'allowed_sources': ['internal'],
        'max_latency_ms': 30000,
        'max_cost_units': 1.0,
        'max_tokens_input': 16000,
        'max_tokens_output': 4000,
        'max_tool_calls': 0,
        'max_agent_steps': 0,
        'max_candidates': 4,
        'required_citations': True,
        'safety_level': 'low',
        'escalation_allowed': True,
        'fallback_policy': 'degrade_to_native',
    },
    'roles': {
        'admin': {
            'allowed_pipelines': ALL_PIPELINES,
            'allowed_tools': ['search', 'calculator', 'graph_query', 'web_fetch'],
            'max_tool_calls': 8,
            'max_agent_steps': 6,
        },
        'user': {},
    },
    'tenants': {},
}


def _merge(base: dict, overlay: dict) -> dict:
    out = dict(base)
    for k, v in (overlay or {}).items():
        out[k] = v
    return out


def load_policy_doc(stored: dict | None) -> dict:
    """Normalize a stored policy document over the shipped default."""
    doc = dict(DEFAULT_POLICY_DOC)
    if isinstance(stored, dict):
        if 'version' in stored:
            doc['version'] = str(stored['version'])
        doc['default'] = _merge(doc['default'], stored.get('default') or {})
        roles = dict(doc['roles'])
        for role, patch in (stored.get('roles') or {}).items():
            roles[role] = _merge(roles.get(role, {}), patch or {})
        doc['roles'] = roles
        tenants = dict(doc.get('tenants') or {})
        for tid, patch in (stored.get('tenants') or {}).items():
            tenants[tid] = _merge(tenants.get(tid, {}), patch or {})
        doc['tenants'] = tenants
    return doc


def pipeline_available(pipeline: str, settings: OrchestratorSettings) -> bool:
    """Feature flags gate which pipelines can ever be allowed (§13.3)."""
    return {
        'native_rag': True,
        'hybrid_rag': settings.hybrid_enabled,
        'graph_rag': settings.graph_enabled,
        'agentic_rag': settings.agentic_enabled,
        'tool_pipeline': settings.web_tools_enabled,
    }.get(pipeline, False)


def evaluate_policy(
    query_context,
    analysis,
    settings: OrchestratorSettings,
    policy_doc: dict | None = None,
) -> PolicyDecision:
    """Produce the §4.2.2 PolicyDecision for one request.

    Inputs are the QueryContext and QueryAnalysis contracts; the engine reads
    role/tenant, request type and risk signals, intersects declared allowances
    with feature flags, and hard-denies unsafe requests before planning.
    """
    doc = policy_doc or DEFAULT_POLICY_DOC
    user = query_context.user_context
    role = user.role or 'user'
    tenant_id = user.tenant_id or ''

    merged = dict(doc['default'])
    merged = _merge(merged, (doc.get('roles') or {}).get(role) or {})
    merged = _merge(merged, (doc.get('tenants') or {}).get(tenant_id) or {})

    decision = PolicyDecision(
        policy_id=f'{tenant_id or "global"}/{role}',
        policy_version=str(doc.get('version', '1')),
        required_citations=bool(merged.get('required_citations', True)),
        fallback_policy=str(merged.get('fallback_policy', 'degrade_to_native')),
        escalation_allowed=bool(merged.get('escalation_allowed', True)),
        max_latency_ms=int(merged.get('max_latency_ms', settings.max_latency_ms)),
        max_cost_units=float(merged.get('max_cost_units', settings.max_cost_units)),
        max_tokens_input=int(merged.get('max_tokens_input', 16000)),
        max_tokens_output=int(merged.get('max_tokens_output', 4000)),
        max_tool_calls=min(int(merged.get('max_tool_calls', 0)), settings.max_tool_calls),
        max_agent_steps=min(int(merged.get('max_agent_steps', 0)), settings.max_agent_steps),
        max_candidates=int(merged.get('max_candidates', settings.max_candidates)),
        allowed_tools=list(merged.get('allowed_tools') or []),
        allowed_sources=list(merged.get('allowed_sources') or ['internal']),
    )

    # Intersect declared pipelines with feature flags — a disabled subsystem is
    # invisible to planning even if a stale policy still lists it.
    allowed = [p for p in (merged.get('allowed_pipelines') or []) if pipeline_available(p, settings)]
    decision.allowed_pipelines = allowed or ['native_rag']

    # Safety: explicit deny paths (§4.2.2 п.10, режим 7 Refusal mode).
    if query_context.safety_flags:
        decision.deny = True
        decision.deny_reason = 'safety: ' + ', '.join(query_context.safety_flags[:4])
        decision.safety_level = 'critical'
        return decision

    # Risk classification from analysis signals.
    risk = float(analysis.safety_risk_score or 0.0)
    domain = (analysis.domain or '').lower()
    if any(d in domain for d in CRITICAL_DOMAINS) or risk >= 0.8:
        decision.safety_level = 'critical'
    elif risk >= 0.5:
        decision.safety_level = 'high'
    elif risk >= 0.2:
        decision.safety_level = 'medium'
    else:
        decision.safety_level = 'low'

    if decision.safety_level == 'critical':
        # Critical domains: no unsupervised agent autonomy above policy,
        # ensemble verification required (§15.8 управление рисками).
        decision.max_agent_steps = min(decision.max_agent_steps, 3)
        decision.required_citations = True
        decision.escalation_allowed = True

    # PII present but tools/web external sources would leak it outward:
    # strip external pipelines unless the tenant policy keeps them on purpose.
    if query_context.pii_flags and 'external' in decision.allowed_sources:
        if decision.safety_level in ('high', 'critical'):
            decision.allowed_pipelines = [p for p in decision.allowed_pipelines if p != 'tool_pipeline']
            decision.allowed_tools = [t for t in decision.allowed_tools if t != 'web_fetch']

    # Non-admin users never get agentic autonomy by default.
    if role != 'admin' and decision.max_agent_steps == 0:
        decision.allowed_pipelines = [p for p in decision.allowed_pipelines if p != 'agentic_rag']

    return decision
