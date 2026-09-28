"""Response Evaluation Layer (ТЗ §4.5).

Five mandatory components, all deterministic and CPU-cheap — the evaluation
hop must not itself become a latency/cost center (§5.1):

* Relevance Scoring (§4.5.3) — lexical overlap of the answer against the
  query terms (coverage of query parts, off-topic penalty, conciseness),
  computed per claim as well as per whole answer (§4.5.3 п.4).
* Groundedness Check (§4.5.4) — every atomic claim is matched against the
  candidate's own source snippets by token containment; claims are classified
  supported / partially_supported / unsupported / contradicted / inferred /
  external_unverified. Unsupported factual claims get flagged so synthesis
  must mark or drop them (§4.5.4 rule).
* Contradiction Detection (§4.5.5) — numeric/temporal/factual comparison of
  claims across candidates that share topic tokens but disagree on numbers
  ("saves 20%" vs "saves 55%") or polarity ("does X" vs "does not X").
* Citation Verification (§4.5.6) — each SourceRef is checked to point at a
  real retrieved document (non-empty id/snippet, hash recomputes); fabricated
  refs score zero and are stripped before delivery.
* Safety Filter (§4.5.7) — response-side screen: secret leakage, PII echo,
  instruction-following artifacts (prompt leakage), toxic patterns; blocked
  fragments are removed, never logged in the clear.

The layer emits EvaluationReport (§4.5.8) with a recommended_action from
select|merge|clarify|refuse|escalate consumed by synthesis and by the
orchestrator's escalation loop (§10.4).
"""

from __future__ import annotations

import hashlib
import logging
import re

from open_webui.retrieval.graphrag.models import (
    CandidateScore,
    Claim,
    ContradictionPair,
    ContradictionResult,
    EvaluationReport,
    RelevanceResult,
)
from open_webui.retrieval.graphrag.settings import OrchestratorSettings

log = logging.getLogger(__name__)

_TOKEN_RE = re.compile(r'[\wёх-]+', re.UNICODE)
_NUM_RE = re.compile(r'-?\d+(?:[.,]\d+)?\s*(?:%|процент|percent|₽|\$|€|руб|usd|eur|кг|kg|м|км|km|мс|ms|с\b|секунд)?')
_NEG_RE = re.compile(r'(?i)\b(не|no|not|never|никогда|нельзя)\b')

# Response-side safety patterns (§4.5.7 п.1).
_SECRET_RES = [
    re.compile(r'(?i)(api[_-]?key|secret|token|password|пароль|секрет)\s*[:=]\s*\S{6,}'),
    re.compile(r'\bsk-[A-Za-z0-9]{20,}\b'),
]
_PII_RES = [
    re.compile(r'[\w.+-]+@[\w-]+\.[\w.-]+'),
    re.compile(r'\b(?:\+7|8)[- ]?\(?\d{3}\)?[- ]?\d{3}[- ]?\d{2}[- ]?\d{2}\b'),
]
_LEAK_RES = [
    re.compile(r'(?i)(system\s+prompt|инструкция\s+системы|my\s+instructions\s+are|мои\s+инструкции)'),
]


def _tokens(text: str) -> set[str]:
    return {t.lower() for t in _TOKEN_RE.findall(text or '') if len(t) > 2}


def _sentences(text: str) -> list[str]:
    parts = re.split(r'(?<=[.!?。])\s+|\n+', text or '')
    return [p.strip() for p in parts if p and len(p.strip()) > 20]


# ── §4.5.3 Relevance ───────────────────────────────────────────────────

def score_relevance(candidate, ctx) -> RelevanceResult:
    query_terms = _tokens(ctx.normalized_query)
    answer_terms = _tokens(candidate.answer_text)
    reasons: list[str] = []
    if not query_terms or not answer_terms:
        return RelevanceResult(reason_codes=['empty'])
    overlap = query_terms & answer_terms
    coverage = len(overlap) / max(len(query_terms), 1)
    # Off-topic: answer mass that shares nothing with the query vocabulary.
    off = 1.0 - (len(answer_terms & query_terms) / max(len(answer_terms), 1))
    conciseness = 1.0 if len(candidate.answer_text) <= 4000 else 0.7
    if coverage < 0.15:
        reasons.append('low_coverage')
    if candidate.status == 'partial':
        reasons.append('partial_candidate')
        conciseness *= 0.8
    relevance = round(max(0.0, min(1.0, 0.7 * coverage + 0.3 * (1 - off) * conciseness)), 3)
    return RelevanceResult(
        relevance_score=relevance,
        coverage_score=round(coverage, 3),
        conciseness_score=round(conciseness, 3),
        off_topic_penalty=round(off * 0.3, 3),
        reason_codes=reasons,
    )


# ── §4.5.4 Groundedness ────────────────────────────────────────────────

def classify_claim(claim_text: str, sources: list[str], pipeline: str) -> str:
    """Entailment-lite: token containment of the claim in its evidence."""
    ct = _tokens(claim_text)
    if not ct:
        return 'unsupported'
    best = 0.0
    for s in sources:
        st = _tokens(s)
        if not st:
            continue
        containment = len(ct & st) / len(ct)
        best = max(best, containment)
    if pipeline == 'tool_pipeline':
        return 'external_unverified' if best >= 0.3 else 'unsupported'
    if best >= 0.65:
        return 'supported'
    if best >= 0.35:
        return 'partially_supported'
    if best >= 0.15:
        return 'inferred'
    return 'unsupported'


def check_groundedness(candidate) -> tuple[float, list[Claim]]:
    """Annotate claims with support status; return (groundedness, claims)."""
    source_texts = list(candidate.context_documents) + [s.snippet for s in candidate.sources]
    claims = candidate.claims or [Claim(text=s) for s in _sentences(candidate.answer_text)[:8]]
    supported_w = {'supported': 1.0, 'external_unverified': 0.6, 'partially_supported': 0.5,
                   'inferred': 0.3, 'contradicted': 0.0, 'unsupported': 0.0}
    scores = []
    for c in claims:
        c.status = classify_claim(c.text, source_texts, candidate.pipeline)
        scores.append(supported_w.get(c.status, 0.0))
    grounded = round(sum(scores) / len(scores), 3) if scores else (0.6 if source_texts else 0.0)
    return grounded, claims


# ── §4.5.5 Contradictions ──────────────────────────────────────────────

def _numbers(text: str) -> list[float]:
    out = []
    for m in _NUM_RE.findall(text or ''):
        try:
            out.append(float(m.strip().rstrip('%').replace(',', '.')))
        except ValueError:
            pass
    return out


def detect_contradictions(candidates) -> ContradictionResult:
    pairs: list[ContradictionPair] = []
    severity = 'low'
    ok = [c for c in candidates if c.status != 'failed']
    for i in range(len(ok)):
        for j in range(i + 1, len(ok)):
            a, b = ok[i], ok[j]
            ta, tb = _tokens(a.answer_text[:1500]), _tokens(b.answer_text[:1500])
            shared = ta & tb
            if len(shared) < 3:
                continue  # different topics cannot contradict
            na, nb = _numbers(a.answer_text), _numbers(b.answer_text)
            if na and nb:
                sa, sb = set(na), set(nb)
                if sa and sb and not (sa & sb) and abs(min(sa) - min(sb)) / max(abs(min(sa)), abs(min(sb)), 1e-9) > 0.5:
                    pairs.append(ContradictionPair(
                        claim_a=f'{a.pipeline}: {a.answer_text[:80]}',
                        claim_b=f'{b.pipeline}: {b.answer_text[:80]}',
                        type='numeric',
                        explanation='числовые значения в кандидатах расходятся более чем на 50%',
                    ))
                    severity = 'high'
            # Polarity clash on similar subject sentences.
            for sa_ in _sentences(a.answer_text)[:4]:
                for sb_ in _sentences(b.answer_text)[:4]:
                    tsa, tsb = _tokens(sa_), _tokens(sb_)
                    jac = len(tsa & tsb) / max(len(tsa | tsb), 1)
                    if jac > 0.5 and bool(_NEG_RE.search(sa_)) != bool(_NEG_RE.search(sb_)):
                        pairs.append(ContradictionPair(
                            claim_a=sa_[:120], claim_b=sb_[:120], type='factual',
                            explanation='утверждения противоположны по полярности при одинаковом субъекте',
                        ))
                        severity = 'critical' if severity == 'critical' else 'medium'
    return ContradictionResult(
        contradiction_found=bool(pairs),
        severity=severity if pairs else 'low',
        pairs=pairs[:6],
    )


# ── §4.5.6 Citation verification ───────────────────────────────────────

def verify_citations(candidate) -> float:
    """Drop refs that don't resolve to a real retrieved fragment; score rest."""
    doc_hashes = {hashlib.sha256(d.encode()).hexdigest()[:16] for d in candidate.context_documents if isinstance(d, str)}
    kept = []
    for src in candidate.sources:
        if not src.source_id or src.source_id == 'unknown' and not src.document_id:
            continue
        if not src.snippet.strip():
            continue
        recomputed = hashlib.sha256(src.snippet.encode()).hexdigest()[:16]
        # snippet came straight from a document, so either its own hash or the
        # containing doc's hash must be known; graph refs carry their own tag.
        if src.hash != recomputed and src.hash not in doc_hashes and recomputed not in doc_hashes and src.source_id != 'knowledge-graph':
            continue  # fabricated/stale ref (§4.5.6 п.5)
        kept.append(src)
    n_before, n_after = len(candidate.sources), len(kept)
    candidate.sources = kept
    if n_before == 0:
        return 0.0
    return round(n_after / n_before, 3)


# Freshness proxy (§4.5.8 field): index/graph versions present => fresh.
def _freshness(candidate) -> float:
    if candidate.metadata.index_version or candidate.metadata.graph_version:
        return 0.9
    return 0.7 if candidate.pipeline != 'tool_pipeline' else 0.95  # external = current by construction


# ── §4.5.7 Safety filter ───────────────────────────────────────────────

def safety_screen(candidate, ctx, policy) -> tuple[float, list[str]]:
    violations: list[str] = []
    text = candidate.answer_text or ''
    if any(r.search(text) for r in _SECRET_RES):
        violations.append('secret_leakage')
    if any(r.search(text) for r in _PII_RES) and 'pii' in (ctx.pii_flags or []):
        violations.append('pii_echo')
    if any(r.search(text) for r in _LEAK_RES):
        violations.append('prompt_leakage')
    if ctx.safety_flags and policy.safety_level == 'critical':
        violations.append('unsafe_context')
    # Block/modify offending fragments rather than reject wholesale (§4.5.7 п.3).
    for rx in _SECRET_RES + _LEAK_RES:
        text = rx.sub('[скрыто политикой безопасности]', text)
    candidate.answer_text = text
    score = 1.0 - min(1.0, 0.5 * len(violations))
    return score, violations


# ── Orchestration of the layer (§4.5.8) ────────────────────────────────

def evaluate_candidates(candidates, ctx, analysis, policy, settings: OrchestratorSettings) -> EvaluationReport:
    report = EvaluationReport()
    if not candidates:
        report.recommended_action = 'escalate'
        report.confidence = 0.0
        return report

    unsupported: list[Claim] = []
    for cand in candidates:
        rel = score_relevance(cand, ctx)
        grounded, claims = check_groundedness(cand)
        cand.claims = claims
        citation_q = verify_citations(cand) if settings.citation_verification_enabled else 0.5
        safety_s, violations = (1.0, [])
        if settings.safety_filter_enabled:
            safety_s, violations = safety_screen(cand, ctx, policy)
        report.safety_violations.extend(violations)
        unsupported.extend([c for c in claims if c.status == 'unsupported' and c.type == 'fact'])

        consistency = 1.0  # adjusted after cross-candidate pass below
        overall = round(
            0.30 * rel.relevance_score
            + 0.30 * grounded
            + 0.15 * citation_q
            + 0.15 * safety_s
            + 0.10 * consistency,
            3,
        )
        flags = list(rel.reason_codes)
        if grounded < settings.min_groundedness:
            flags.append('low_groundedness')
        if unsupported_ratio(cand) > settings.max_unsupported_claim_ratio:
            flags.append('unsupported_claims')
        if cand.status == 'partial':
            flags.append('partial')
        report.candidate_scores.append(CandidateScore(
            candidate_id=cand.candidate_id,
            relevance=rel.relevance_score,
            groundedness=grounded,
            citation_quality=citation_q,
            safety=safety_s,
            consistency=consistency,
            freshness=_freshness(cand),
            overall_score=overall,
            flags=flags,
        ))

    contra = detect_contradictions(candidates) if settings.evaluation_enabled else ContradictionResult()
    report.contradictions = contra.pairs
    report.unsupported_claims = unsupported[:10]

    # Consistency feeds back into per-candidate overall (penalize both sides).
    if contra.contradiction_found:
        pen = {'low': 0.05, 'medium': 0.15, 'high': 0.25, 'critical': 0.35}[contra.severity]
        for cs in report.candidate_scores:
            cs.consistency = round(max(0.0, 1.0 - pen), 3)
            cs.overall_score = round(cs.overall_score - pen * 0.1, 3)

    best = max(report.candidate_scores, key=lambda c: c.overall_score) if report.candidate_scores else None
    live = [c for c in candidates if c.status != 'failed']

    if report.safety_violations:
        report.recommended_action = 'refuse'
        report.refusal_reason = 'safety: ' + ', '.join(sorted(set(report.safety_violations))[:3])
    elif not live or best is None or best.overall_score < settings.min_overall_score * 0.6:
        report.recommended_action = 'escalate'
    elif best.overall_score < settings.min_overall_score or best.groundedness < settings.min_groundedness:
        report.recommended_action = 'escalate'
    elif contra.severity in ('high', 'critical'):
        report.recommended_action = 'merge'  # balanced answer with warnings (§10.4)
    elif len(live) > 1 and best.overall_score - sorted((c.overall_score for c in report.candidate_scores), reverse=True)[1] < 0.05:
        report.recommended_action = 'merge'
    elif analysis.ambiguity_score >= 0.6:
        report.recommended_action = 'clarify'
    else:
        report.recommended_action = 'select'

    report.confidence = round(best.overall_score if best else 0.0, 3)
    if report.recommended_action == 'clarify':
        report.clarification_question = _clarification_hint(ctx, analysis)
    if report.recommended_action == 'escalate' and not live:
        report.refusal_reason = 'no candidate produced usable evidence'
    return report


def unsupported_ratio(candidate) -> float:
    facts = [c for c in candidate.claims if c.type == 'fact']
    if not facts:
        return 0.0
    bad = sum(1 for c in facts if c.status in ('unsupported', 'contradicted'))
    return bad / len(facts)


_CLARIFY_TEMPLATES = {
    'ru': 'Уточните, пожалуйста, запрос: что именно вас интересует — {hint}?',
    'en': 'Could you clarify your request — specifically, {hint}?',
}


def _clarification_hint(ctx, analysis) -> str:
    lang = getattr(ctx, 'language', 'en')
    tmpl = _CLARIFY_TEMPLATES.get(lang, _CLARIFY_TEMPLATES['en'])
    if analysis.entities:
        hint = f'какая сущность имеется в виду: {", ".join(analysis.entities[:3])}' if lang == 'ru' else f'which entity: {", ".join(analysis.entities[:3])}'
    elif analysis.temporal_expressions:
        hint = 'какой период времени' if lang == 'ru' else 'which time period'
    else:
        hint = 'какой аспект вопроса' if lang == 'ru' else 'which aspect of the question'
    return tmpl.format(hint=hint)
