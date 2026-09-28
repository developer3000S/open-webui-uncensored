"""Data model of the adaptive RAG orchestrator (ТЗ §9).

Pydantic mirrors of every contract object named in docs/RAG-ТЗ.md:
QueryContext (§4.1.4), QueryAnalysis (§4.2.3), PolicyDecision (§4.2.2),
ConfidenceEstimate (§4.2.4), ExecutionPlan (§4.2.5), CandidateResponse
(§4.4.3), EvaluationReport (§4.5.8), FinalResponse (§4.6.4) and TraceRecord
(§9.8). Field names follow the document's JSON shapes verbatim so traces are
replayable against the ТЗ contracts; unknown extras are allowed, not rejected,
so forward-compatible payloads survive a round-trip.
"""

from __future__ import annotations

import time
import uuid
from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


def new_id() -> str:
    return str(uuid.uuid4())


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class ContractModel(BaseModel):
    """Base for every cross-layer object: tolerant to extra fields."""

    model_config = ConfigDict(extra='allow')


# ── §4.1.4 QueryContext ────────────────────────────────────────────────


class UserContext(ContractModel):
    user_id: str | None = None
    tenant_id: str | None = None
    role: str | None = None
    roles: list[str] = Field(default_factory=list)
    permissions: list[str] = Field(default_factory=list)


class QueryFeatures(ContractModel):
    """Basic features extracted by preprocessing (ТЗ §4.1.2 п.7)."""

    length_chars: int = 0
    word_count: int = 0
    is_question: bool = False
    has_negation: bool = False
    has_temporal_expression: bool = False
    has_numeric: bool = False
    has_proper_names: bool = False
    has_anaphoric_reference: bool = False
    instruction_only: bool = False


class QueryContext(ContractModel):
    request_id: str = Field(default_factory=new_id)
    trace_id: str = Field(default_factory=new_id)
    timestamp: str = Field(default_factory=now_iso)
    raw_query: str = ''
    normalized_query: str = ''
    language: str = 'en'
    session_id: str | None = None
    conversation_history: list[dict] = Field(default_factory=list)
    user_context: UserContext = Field(default_factory=UserContext)
    attachments: list[Any] = Field(default_factory=list)
    detected_entities: list[str] = Field(default_factory=list)
    pii_flags: list[str] = Field(default_factory=list)
    safety_flags: list[str] = Field(default_factory=list)
    cache_key: str | None = None
    token_count: int = 0
    features: QueryFeatures = Field(default_factory=QueryFeatures)
    items: list[dict] = Field(default_factory=list)


# ── §4.2.3 QueryAnalysis ───────────────────────────────────────────────

IntentType = Literal[
    'simple_fact',
    'definition',
    'procedural',
    'comparative',
    'causal',
    'temporal',
    'multi_hop',
    'graph_relation',
    'summary',
    'analysis',
    'calculation',
    'external_lookup',
    'ambiguous',
    'unsupported',
    'unsafe',
    'conversational',
]

Complexity = Literal['low', 'medium', 'high', 'very_high']


class QueryAnalysis(ContractModel):
    intent: IntentType = 'simple_fact'
    domain: str | None = None
    complexity: Complexity = 'low'
    requires_exact_match: bool = False
    requires_semantic_search: bool = True
    requires_graph: bool = False
    requires_multi_step: bool = False
    requires_external_data: bool = False
    requires_calculation: bool = False
    requires_comparison: bool = False
    ambiguity_score: float = 0.0
    answerability_score: float = 1.0
    safety_risk_score: float = 0.0
    clarification_recommended: bool = False
    entities: list[str] = Field(default_factory=list)
    relations: list[list[str]] = Field(default_factory=list)
    temporal_expressions: list[str] = Field(default_factory=list)
    evidence_hypotheses: list[str] = Field(default_factory=list)
    intent_confidences: dict[str, float] = Field(default_factory=dict)


# ── §4.2.2 PolicyDecision ──────────────────────────────────────────────

SafetyLevel = Literal['low', 'medium', 'high', 'critical']


class Budgets(ContractModel):
    max_latency_ms: int = 0
    max_cost_units: float = 0.0
    max_tokens_input: int = 0
    max_tokens_output: int = 0
    max_tool_calls: int = 0
    max_agent_steps: int = 0
    max_candidates: int = 0


class PolicyDecision(ContractModel, Budgets):
    policy_id: str = 'default'
    policy_version: str = '1'
    deny: bool = False
    deny_reason: str | None = None
    allowed_pipelines: list[str] = Field(default_factory=list)
    allowed_tools: list[str] = Field(default_factory=list)
    allowed_sources: list[str] = Field(default_factory=list)
    required_citations: bool = True
    safety_level: SafetyLevel = 'low'
    escalation_allowed: bool = True
    fallback_policy: str = 'degrade_to_native'
    mode_override: str | None = None


# ── §4.2.4 ConfidenceEstimate ──────────────────────────────────────────

ProcessingMode = Literal[
    'fast_path', 'standard', 'deep', 'ensemble', 'clarification_required', 'refusal_recommended'
]


class ConfidenceEstimate(ContractModel):
    routing_confidence: float = 0.5
    estimated_success_probability: float = 0.5
    estimated_latency_ms: int = 0
    estimated_cost_units: float = 0.0
    recommended_mode: ProcessingMode = 'standard'
    reason_codes: list[str] = Field(default_factory=list)


# ── §4.2.5 ExecutionPlan ───────────────────────────────────────────────

PipelineName = Literal['native_rag', 'graph_rag', 'agentic_rag', 'hybrid_rag', 'tool_pipeline']
PlanMode = Literal['single', 'parallel', 'sequential', 'conditional', 'agentic', 'clarify', 'refuse']


class RetryPolicy(ContractModel):
    attempts: int = 1
    backoff_ms: int = 250


class PlanTask(ContractModel):
    task_id: str = Field(default_factory=new_id)
    pipeline: PipelineName = 'native_rag'
    depends_on: list[str] = Field(default_factory=list)
    timeout_ms: int = 20000
    retry_policy: RetryPolicy = Field(default_factory=RetryPolicy)
    budget: dict[str, Any] = Field(default_factory=dict)
    parameters: dict[str, Any] = Field(default_factory=dict)
    condition: str | None = None
    priority: int = 5
    # Audit trail: why this node entered the plan (ТЗ §4.2.5 п.10, §15.6).
    reason: str = ''


class ExecutionPlan(ContractModel):
    plan_id: str = Field(default_factory=new_id)
    mode: PlanMode = 'single'
    tasks: list[PlanTask] = Field(default_factory=list)
    global_timeout_ms: int = 30000
    global_budget: dict[str, Any] = Field(default_factory=dict)
    fallback_plan: list[PlanTask] = Field(default_factory=list)
    rationale: list[str] = Field(default_factory=list)


# ── §4.4.3 CandidateResponse ───────────────────────────────────────────

ClaimType = Literal['fact', 'opinion', 'hypothesis', 'calculation', 'recommendation']
ClaimStatus = Literal[
    'supported', 'partially_supported', 'unsupported', 'contradicted', 'inferred', 'external_unverified'
]


class Claim(ContractModel):
    claim_id: str = Field(default_factory=new_id)
    text: str = ''
    type: ClaimType = 'fact'
    status: ClaimStatus | None = None
    source_refs: list[str] = Field(default_factory=list)


class SourceRef(ContractModel):
    source_id: str = ''
    document_id: str | None = None
    chunk_id: str | None = None
    uri: str | None = None
    title: str | None = None
    snippet: str = ''
    offset_start: int = 0
    offset_end: int = 0
    score: float = 0.0
    version: str | None = None
    hash: str | None = None
    access_level: str | None = None


class CandidateMetadata(ContractModel):
    latency_ms: int = 0
    cost_units: float = 0.0
    tokens_input: int = 0
    tokens_output: int = 0
    model_version: str | None = None
    prompt_version: str | None = None
    index_version: str | None = None
    graph_version: str | None = None


class CandidateResponse(ContractModel):
    candidate_id: str = Field(default_factory=new_id)
    pipeline: str = 'native_rag'
    task_id: str | None = None
    answer_text: str = ''
    context_documents: list[str] = Field(default_factory=list)
    context_metadatas: list[dict] = Field(default_factory=list)
    claims: list[Claim] = Field(default_factory=list)
    sources: list[SourceRef] = Field(default_factory=list)
    metadata: CandidateMetadata = Field(default_factory=CandidateMetadata)
    self_confidence: float = 0.0
    status: Literal['success', 'partial', 'failed'] = 'success'
    error_code: str | None = None
    steps: list[dict] = Field(default_factory=list)


# ── §4.5 Evaluation layer outputs ──────────────────────────────────────


class RelevanceResult(ContractModel):
    relevance_score: float = 0.0
    coverage_score: float = 0.0
    conciseness_score: float = 0.0
    off_topic_penalty: float = 0.0
    reason_codes: list[str] = Field(default_factory=list)


class ContradictionPair(ContractModel):
    claim_a: str = ''
    claim_b: str = ''
    type: Literal['numeric', 'temporal', 'factual', 'logical', 'terminological', 'interpretation'] = 'factual'
    explanation: str = ''


class ContradictionResult(ContractModel):
    contradiction_found: bool = False
    severity: Literal['low', 'medium', 'high', 'critical'] = 'low'
    pairs: list[ContradictionPair] = Field(default_factory=list)


class CandidateScore(ContractModel):
    candidate_id: str = ''
    relevance: float = 0.0
    groundedness: float = 0.0
    citation_quality: float = 0.0
    safety: float = 1.0
    consistency: float = 1.0
    freshness: float = 1.0
    overall_score: float = 0.0
    flags: list[str] = Field(default_factory=list)


RecommendedAction = Literal['select', 'merge', 'clarify', 'refuse', 'escalate']


class EvaluationReport(ContractModel):
    evaluation_id: str = Field(default_factory=new_id)
    candidate_scores: list[CandidateScore] = Field(default_factory=list)
    contradictions: list[ContradictionPair] = Field(default_factory=list)
    unsupported_claims: list[Claim] = Field(default_factory=list)
    safety_violations: list[str] = Field(default_factory=list)
    recommended_action: RecommendedAction = 'select'
    confidence: float = 0.0
    clarification_question: str | None = None
    refusal_reason: str | None = None


# ── §4.6.4 FinalResponse ───────────────────────────────────────────────

ResponseStatus = Literal['answered', 'clarification', 'uncertain', 'refused', 'partial']


class Usage(ContractModel):
    latency_ms: int = 0
    cost_units: float = 0.0
    tokens_input: int = 0
    tokens_output: int = 0


class FinalResponse(ContractModel):
    response_id: str = Field(default_factory=new_id)
    request_id: str = ''
    trace_id: str = ''
    answer_text: str = ''
    citations: list[dict] = Field(default_factory=list)
    confidence: float = 0.0
    status: ResponseStatus = 'answered'
    warnings: list[str] = Field(default_factory=list)
    used_pipelines: list[str] = Field(default_factory=list)
    sources_summary: list[dict] = Field(default_factory=list)
    ui_hints: dict[str, Any] = Field(default_factory=dict)
    usage: Usage = Field(default_factory=Usage)


# ── §9.8 TraceRecord ───────────────────────────────────────────────────


class PipelineRun(ContractModel):
    task_id: str = ''
    pipeline: str = ''
    started_at: float = Field(default_factory=time.time)
    duration_ms: int = 0
    status: str = 'success'
    error_code: str | None = None
    notes: list[str] = Field(default_factory=list)


class TraceRecord(ContractModel):
    trace_id: str = ''
    request_id: str = ''
    tenant_id: str | None = None
    user_id: str | None = None
    started_at: str = Field(default_factory=now_iso)
    ended_at: str | None = None
    total_latency_ms: int = 0
    total_cost_units: float = 0.0
    query_analysis: dict[str, Any] = Field(default_factory=dict)
    policy_decision: dict[str, Any] = Field(default_factory=dict)
    execution_plan: dict[str, Any] = Field(default_factory=dict)
    pipeline_runs: list[dict] = Field(default_factory=list)
    candidates: list[dict] = Field(default_factory=list)
    evaluation_report: dict[str, Any] = Field(default_factory=dict)
    final_response: dict[str, Any] = Field(default_factory=dict)
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    versions: dict[str, Any] = Field(default_factory=dict)


# ── Feedback (§4.7) ────────────────────────────────────────────────────


class FeedbackRecord(ContractModel):
    feedback_id: str = Field(default_factory=new_id)
    trace_id: str = ''
    response_id: str | None = None
    rating: int | None = None  # -1 / +1 explicit thumbs; 1..5 usefulness
    kind: Literal['explicit', 'implicit'] = 'explicit'
    signal: str | None = None  # e.g. repeat_query, copied, refused_clarification, human_escalation
    comment: str | None = None
    created_at: str = Field(default_factory=now_iso)
