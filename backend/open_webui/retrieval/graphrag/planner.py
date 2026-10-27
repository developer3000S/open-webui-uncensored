"""Execution Planner (ТЗ §4.2.5): minimal-sufficient plan from analysis+policy.

The routing matrix below is the §10.1 table expressed as data — intent ->
candidate pipelines in preference order. The planner intersects candidates
with PolicyDecision.allowed_pipelines, picks a plan mode from the confidence
estimate (§4.2.4 thresholds), attaches per-task timeouts/budgets (§5.1.3) and
records WHY every task entered the plan (explainability, §15.6). Escalation
(§10.2) produces a follow-up plan along the default ladder:
Native -> Hybrid/Graph-assisted -> Graph or Agentic -> full ensemble.
"""

from __future__ import annotations

from open_webui.retrieval.graphrag.models import (
    ConfidenceEstimate,
    ExecutionPlan,
    PlanTask,
    PolicyDecision,
    QueryAnalysis,
    RetryPolicy,
)
from open_webui.retrieval.graphrag.settings import OrchestratorSettings, pipeline_timeout

# §10.1 routing matrix: intent -> preferred pipelines, cheapest-first.
ROUTING_MATRIX: dict[str, list[str]] = {
    'simple_fact': ['native_rag'],
    'definition': ['native_rag', 'hybrid_rag'],
    'procedural': ['native_rag', 'agentic_rag'],
    'comparative': ['native_rag', 'hybrid_rag', 'graph_rag', 'agentic_rag'],
    'causal': ['graph_rag', 'hybrid_rag'],
    'temporal': ['native_rag', 'tool_pipeline'],
    'multi_hop': ['agentic_rag', 'native_rag', 'graph_rag'],
    'graph_relation': ['graph_rag', 'native_rag'],
    'summary': ['graph_rag', 'hybrid_rag'],
    'analysis': ['agentic_rag', 'hybrid_rag', 'graph_rag'],
    'calculation': ['agentic_rag', 'tool_pipeline'],
    'external_lookup': ['tool_pipeline', 'native_rag'],
    'ambiguous': [],          # clarification path, no retrieval
    'unsupported': [],        # uncertainty/refusal path
    'unsafe': [],             # refusal path
    'conversational': [],     # answer without retrieval
}

# §10.2 default escalation order.
ESCALATION_LADDER = ['native_rag', 'hybrid_rag', 'graph_rag', 'agentic_rag']


def _allowed(candidates: list[str], policy: PolicyDecision) -> list[str]:
    return [p for p in candidates if p in (policy.allowed_pipelines or [])]


def build_plan(
    analysis: QueryAnalysis,
    policy: PolicyDecision,
    confidence: ConfidenceEstimate,
    settings: OrchestratorSettings,
) -> ExecutionPlan:
    """Compose the initial ExecutionPlan for one request."""
    mode = confidence.recommended_mode
    rationale: list[str] = []

    if mode == 'refusal_recommended' or analysis.intent == 'unsafe':
        rationale.append('refusal: safety risk above threshold')
        return ExecutionPlan(mode='refuse', tasks=[], rationale=rationale)
    if mode == 'clarification_required' or analysis.intent in ('ambiguous', 'unsupported'):
        rationale.append('clarification: ambiguity or missing data precludes retrieval')
        return ExecutionPlan(mode='clarify', tasks=[], rationale=rationale)
    if analysis.intent == 'conversational':
        rationale.append('conversational: no retrieval needed')
        return ExecutionPlan(mode='single', tasks=[], rationale=rationale)

    matrix_row = ROUTING_MATRIX.get(analysis.intent, ['native_rag'])
    candidates = _allowed(matrix_row, policy)
    if not candidates and 'native_rag' in (policy.allowed_pipelines or []):
        candidates = ['native_rag']  # native is always the floor when allowed
    rationale.append(f'matrix[{analysis.intent}] -> {matrix_row}')

    if mode == 'fast_path':
        selected = candidates[:1] or ['native_rag']
        plan_mode = 'single'
        rationale.append(f'confidence {confidence.routing_confidence:.2f} >= {settings.conf_single} -> single pipeline')
    elif mode == 'standard':
        selected = candidates[:2]
        plan_mode = 'parallel' if len(selected) > 1 else 'single'
        rationale.append('standard mode: primary + first alternative')
    elif mode == 'deep':
        selected = _allowed(ESCALATION_LADDER, policy)[:3] or candidates
        plan_mode = 'sequential'
        rationale.append('deep mode: staged escalation within one plan')
    else:  # ensemble
        selected = _allowed(ESCALATION_LADDER, policy)
        plan_mode = 'parallel'
        rationale.append('ensemble mode: all affordable pipelines, evaluator decides')

    selected = [p for p in selected if p in (policy.allowed_pipelines or [])] or ['native_rag']

    tasks: list[PlanTask] = []
    prev_id: str | None = None
    spent_cost = 0.0
    spent_latency = 0
    budget_left_ms = policy.max_latency_ms or settings.max_latency_ms
    budget_left_cost = policy.max_cost_units or settings.max_cost_units
    for i, pipeline in enumerate(selected):
        timeout = pipeline_timeout(settings, pipeline)
        est_cost = {'native_rag': 0.05, 'hybrid_rag': 0.12, 'graph_rag': 0.15, 'agentic_rag': 0.6, 'tool_pipeline': 0.2}[pipeline]
        # Budget guard (§15.1): stop adding nodes that cannot fit remaining budget.
        if spent_latency + timeout > budget_left_ms or spent_cost + est_cost > budget_left_cost:
            if tasks:  # never drop the whole plan — keep what fits
                rationale.append(f'budget cut: dropped {pipeline} (latency/cost ceiling)')
                break
        if pipeline == 'agentic_rag' and policy.max_agent_steps <= 0:
            rationale.append('agentic dropped: policy grants zero agent steps')
            continue
        task = PlanTask(
            pipeline=pipeline,
            timeout_ms=min(timeout, max(budget_left_ms - spent_latency, 1500)),
            retry_policy=RetryPolicy(attempts=1 if pipeline != 'native_rag' else 2),
            budget={'max_cost_units': est_cost},
            priority=1 if pipeline == 'native_rag' else i + 2,
            depends_on=[prev_id] if plan_mode == 'sequential' and prev_id else [],
            reason=f'intent={analysis.intent}, mode={mode}',
        )
        if pipeline == 'agentic_rag':
            task.parameters = {'max_steps': min(policy.max_agent_steps or settings.max_agent_steps, settings.max_agent_steps)}
        if pipeline == 'tool_pipeline':
            task.parameters = {'allowed_tools': policy.allowed_tools}
        tasks.append(task)
        prev_id = task.task_id
        spent_latency += timeout
        spent_cost += est_cost

    if plan_mode == 'sequential' and len(tasks) < 2:
        plan_mode = 'single'

    return ExecutionPlan(
        mode=plan_mode,
        tasks=tasks,
        global_timeout_ms=min(budget_left_ms, settings.max_latency_ms),
        global_budget={'max_cost_units': budget_left_cost, 'max_candidates': policy.max_candidates or settings.max_candidates},
        fallback_plan=[PlanTask(pipeline='native_rag', reason='fallback: degrade to native (§10.2 policy)')]
        if 'native_rag' in (policy.allowed_pipelines or []) else [],
        rationale=rationale,
    )


def escalate_plan(
    original: ExecutionPlan,
    analysis: QueryAnalysis,
    policy: PolicyDecision,
    settings: OrchestratorSettings,
) -> ExecutionPlan | None:
    """Next rung of the §10.2 ladder; None when de-escalation applies (§10.3)."""
    if not policy.escalation_allowed:
        return None
    used = {t.pipeline for t in original.tasks}
    if len(used) >= settings.max_candidates:
        return None  # candidate pool already wide enough
    next_pipeline = None
    for p in ESCALATION_LADDER:
        if p not in used and p in (policy.allowed_pipelines or []):
            next_pipeline = p
            break
    if next_pipeline is None and 'tool_pipeline' not in used and 'tool_pipeline' in (policy.allowed_pipelines or []):
        next_pipeline = 'tool_pipeline'
    if next_pipeline is None:
        return None  # nothing left to add: further sources wouldn't help (§10.3)
    if next_pipeline == 'agentic_rag' and policy.max_agent_steps <= 0:
        return None
    task = PlanTask(
        pipeline=next_pipeline,
        timeout_ms=pipeline_timeout(settings, next_pipeline),
        priority=1,
        reason='escalation: primary candidates scored below threshold (§10.2)',
        parameters={'max_steps': policy.max_agent_steps} if next_pipeline == 'agentic_rag' else {},
    )
    return ExecutionPlan(
        mode='single',
        tasks=[task],
        global_timeout_ms=task.timeout_ms,
        rationale=[f'escalate {sorted(used)} -> {next_pipeline}'],
    )
