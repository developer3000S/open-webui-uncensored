"""Escalation ladder (§10.2) and de-escalation predicate (§10.3/§10.4)."""

from open_webui.retrieval.graphrag.execution import insufficient
from open_webui.retrieval.graphrag.models import (
    CandidateMetadata,
    CandidateResponse,
    ExecutionPlan,
    PlanTask,
    PolicyDecision,
)
from open_webui.retrieval.graphrag.planner import escalate_plan
from open_webui.retrieval.graphrag.settings import OrchestratorSettings


class FakeAnalysis:
    intent = 'factual_lookup'
    complexity = 'simple'


def _cand(conf=0.9, latency=100, text='ответ', status='success'):
    return CandidateResponse(
        pipeline='native_rag',
        status=status,
        answer_text=text,
        self_confidence=conf,
        metadata=CandidateMetadata(latency_ms=latency),
    )


def _policy(allowed, escalation=True, agent_steps=6):
    return PolicyDecision(allowed_pipelines=allowed, escalation_allowed=escalation, max_agent_steps=agent_steps)


def _plan(pipelines):
    return ExecutionPlan(mode='single', tasks=[PlanTask(pipeline=p) for p in pipelines])


def test_insufficient_low_confidence():
    assert insufficient([_cand(conf=0.2)], OrchestratorSettings())


def test_insufficient_empty_stub():
    # zero latency AND no text => ran but produced nothing
    assert insufficient([_cand(latency=0, text='')], OrchestratorSettings())


def test_sufficient_candidate():
    assert not insufficient([_cand(conf=0.8)], OrchestratorSettings())


def test_all_failed_is_insufficient():
    assert insufficient([_cand(status='failed')], OrchestratorSettings())


def test_ladder_climbs_strictly_upward():
    s = OrchestratorSettings(hybrid_enabled=True, graph_enabled=True, agentic_enabled=True)
    policy = _policy(['native_rag', 'hybrid_rag', 'graph_rag', 'agentic_rag'])
    # escalate_plan reports the *new* rung; the caller (orchestration §10.4)
    # accumulates it into the pool — track cumulative coverage here.
    plan = _plan(['native_rag'])
    seen = ['native_rag']
    for _ in range(5):
        nxt = escalate_plan(plan, FakeAnalysis(), policy, s)
        if nxt is None:
            break
        new = [t.pipeline for t in nxt.tasks]
        assert all(p not in seen for p in new), f'ladder repeated {new} (seen={seen})'
        seen += new
        plan = ExecutionPlan(mode='single', tasks=plan.tasks + nxt.tasks)
    assert seen == ['native_rag', 'hybrid_rag', 'graph_rag', 'agentic_rag']


def test_no_escalation_when_disallowed():
    s = OrchestratorSettings()
    assert escalate_plan(_plan(['native_rag']), FakeAnalysis(), _policy(['native_rag'], escalation=False), s) is None


def test_no_escalation_when_exhausted():
    s = OrchestratorSettings(hybrid_enabled=False, graph_enabled=False, agentic_enabled=False)
    assert escalate_plan(_plan(['native_rag']), FakeAnalysis(), _policy(['native_rag']), s) is None


def test_agentic_blocked_without_steps():
    s = OrchestratorSettings(agentic_enabled=True)
    policy = _policy(['native_rag', 'agentic_rag'], agent_steps=0)
    assert escalate_plan(_plan(['native_rag']), FakeAnalysis(), policy, s) is None
