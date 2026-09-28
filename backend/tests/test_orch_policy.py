"""Policy Engine deny-matrix tests (ТЗ §4.2.2)."""

import pytest

from open_webui.retrieval.graphrag.models import QueryContext, UserContext
from open_webui.retrieval.graphrag.policy import evaluate_policy
from open_webui.retrieval.graphrag.settings import OrchestratorSettings


class FakeAnalysis:
    def __init__(self, risk=0.0, domain=''):
        self.safety_risk_score = risk
        self.domain = domain


def _ctx(safety_flags=None, pii_flags=None, role='user', tenant=''):
    return QueryContext(
        original_query='q',
        normalized_query='q',
        user_context=UserContext(user_id='u', role=role, tenant_id=tenant),
        safety_flags=safety_flags or [],
        pii_flags=pii_flags or [],
    )


@pytest.fixture()
def settings():
    return OrchestratorSettings()


def test_safety_flags_deny(settings):
    d = evaluate_policy(_ctx(safety_flags=['instruction_override']), FakeAnalysis(), settings)
    assert d.deny and 'safety' in d.deny_reason and d.safety_level == 'critical'


def test_high_risk_caps_autonomy_on_critical_domain(settings):
    # critical risk => safety_level critical; agent steps capped, citations forced
    s = OrchestratorSettings(agentic_enabled=True)
    d = evaluate_policy(_ctx(role='admin'), FakeAnalysis(risk=0.9), s)
    assert not d.deny  # only explicit safety flags hard-deny
    assert d.safety_level == 'critical'
    assert d.max_agent_steps <= 3 and d.required_citations


def test_disabled_pipeline_never_allowed(settings):
    s = OrchestratorSettings(agentic_enabled=False, graph_enabled=False, hybrid_enabled=False)
    d = evaluate_policy(_ctx(role='admin'), FakeAnalysis(), s)
    assert set(d.allowed_pipelines) == {'native_rag'}


def test_admin_gets_all_when_enabled(settings):
    s = OrchestratorSettings(agentic_enabled=True, graph_enabled=True, web_tools_enabled=True)
    d = evaluate_policy(_ctx(role='admin'), FakeAnalysis(), s)
    assert 'agentic_rag' in d.allowed_pipelines and 'graph_rag' in d.allowed_pipelines


def test_non_admin_loses_agentic_without_steps(settings):
    s = OrchestratorSettings(agentic_enabled=True)
    d = evaluate_policy(_ctx(role='user'), FakeAnalysis(), s)
    assert 'agentic_rag' not in d.allowed_pipelines


def test_pii_strips_external_on_high_risk(settings):
    from open_webui.retrieval.graphrag.policy import load_policy_doc

    # tenant overlay grants the admin pipeline/tool set AND external sources;
    # PII + high risk must still strip external ones (§6.2).
    doc = load_policy_doc(
        {
            'version': '2',
            'tenants': {
                't1': {
                    'allowed_pipelines': ['native_rag', 'hybrid_rag', 'tool_pipeline'],
                    'allowed_tools': ['search', 'web_fetch'],
                    'allowed_sources': ['internal', 'external'],
                }
            },
        }
    )
    s = OrchestratorSettings(web_tools_enabled=True)
    ctx = _ctx(pii_flags=['email'], role='user', tenant='t1')
    d = evaluate_policy(ctx, FakeAnalysis(risk=0.6, domain='hr'), s, policy_doc=doc)
    assert 'tool_pipeline' not in d.allowed_pipelines and 'web_fetch' not in d.allowed_tools


def test_no_pii_keeps_external_for_admin(settings):
    s = OrchestratorSettings(web_tools_enabled=True)
    d = evaluate_policy(_ctx(role='admin'), FakeAnalysis(), s)
    assert 'tool_pipeline' in d.allowed_pipelines
