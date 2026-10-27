"""Response Synthesis Layer (ТЗ §4.6).

Turns the candidate pool + EvaluationReport into the FinalResponse contract:
select / merge / clarify / uncertain / refuse (§4.6.2), with citations and
provenance preserved in every branch (§4.6.3). Merge never invents claims —
it concatenates verified evidence blocks from complementary candidates under a
shared source list (§4.6.2 п.2 "не должна создавать новые фактические
утверждения").

The layer is also where the retrieval product meets this deployment's chat
pipeline: `answer_text` is the grounded evidence digest handed to the model as
context, `sources_summary` mirrors the legacy source shape so downstream
citation UI keeps working, and `ui_hints` carries status/confidence for §15.15
(управление ожиданиями: uncertainty must be visible, not silently smoothed).
"""

from __future__ import annotations

import logging

from open_webui.retrieval.graphrag.models import (
    CandidateResponse,
    EvaluationReport,
    FinalResponse,
    QueryContext,
    Usage,
)
from open_webui.retrieval.graphrag.settings import OrchestratorSettings

log = logging.getLogger(__name__)

_REFUSAL_TEMPLATES = {
    'ru': 'Я не могу ответить на этот запрос. {reason} Если вопрос можно переформулировать в безопасных границах — уточните, и я постараюсь помочь.',
    'en': 'I cannot answer this request. {reason} If it can be rephrased within safe boundaries, please clarify and I will try to help.',
}
_UNCERTAIN_PREFIX_RU = 'Недостаточно данных для однозначного ответа. Возможный частичный ответ ниже; утверждения без подтверждения источниками помечены.'
_UNCERTAIN_PREFIX_EN = 'Insufficient data for a definitive answer. A partial answer follows; claims lacking source support are marked.'


def _citations(candidates: list[CandidateResponse]) -> list[dict]:
    """Claim→source→fragment map (§4.5.6 п.6) rendered as citation entries."""
    out: list[dict] = []
    seen: set[tuple] = set()
    for c in candidates:
        for src in c.sources:
            key = (src.document_id, src.source_id, src.snippet[:60])
            if key in seen:
                continue
            seen.add(key)
            out.append(
                {
                    'source_id': src.source_id,
                    'document_id': src.document_id,
                    'chunk_id': src.chunk_id,
                    'uri': src.uri,
                    'title': src.title,
                    'snippet': src.snippet[:240],
                    'score': src.score,
                    'pipeline': c.pipeline,
                    'hash': src.hash,
                    'access_level': src.access_level,
                }
            )
    return out[:20]


def _sources_summary(candidates: list[CandidateResponse]) -> list[dict]:
    """Legacy-compatible {document, metadata, source-name} rows for the chat
    citation panel; graph provenance stays labeled as knowledge-graph."""
    rows: list[dict] = []
    for c in candidates:
        if c.status == 'failed':
            continue
        docs = c.context_documents or [c.answer_text]
        metas = c.context_metadatas or [{} for _ in docs]
        rows.append({'documents': docs, 'metadatas': metas, 'pipeline': c.pipeline})
    return rows


def _warnings(report: EvaluationReport, candidates: list[CandidateResponse]) -> list[str]:
    warnings: list[str] = []
    for p in report.contradictions[:4]:
        warnings.append(f'противоречие ({p.type}): {p.explanation}')
    if report.unsupported_claims:
        warnings.append(
            f'{len(report.unsupported_claims)} неподтверждённых утверждений исключены или помечены (§4.5.4)')
    external = [c for c in candidates if c.pipeline == 'tool_pipeline' and c.status != 'failed']
    if external:
        warnings.append('использованы внешние данные — точность не гарантирована источником (§4.6.3)')
    return warnings


def synthesize(
    ctx: QueryContext,
    candidates: list[CandidateResponse],
    report: EvaluationReport,
    policy,
    settings: OrchestratorSettings,
    used_pipelines: list[str],
    usage: Usage,
) -> FinalResponse:
    lang = ctx.language or 'en'
    live = [c for c in candidates if c.status != 'failed']
    by_id = {c.candidate_id: c for c in live}

    resp = FinalResponse(
        request_id=ctx.request_id,
        trace_id=ctx.trace_id,
        confidence=round(report.confidence, 3),
        used_pipelines=sorted(set(used_pipelines)),
        usage=usage,
        ui_hints={'routing_rationale_expected': True},
    )

    action = report.recommended_action

    # ── Refuse (§4.6.2 п.5) ────────────────────────────────────────────
    if action == 'refuse' or policy.deny:
        reason = report.refusal_reason or (policy.deny_reason if policy.deny else '') or ''
        tmpl = _REFUSAL_TEMPLATES.get(lang, _REFUSAL_TEMPLATES['en'])
        resp.status = 'refused'
        resp.answer_text = tmpl.format(reason=reason)
        resp.warnings = [reason] if reason else []
        resp.ui_hints['fallback_offered'] = True
        return resp

    # ── Clarify (§4.6.2 п.3) ───────────────────────────────────────────
    if action == 'clarify':
        resp.status = 'clarification'
        resp.answer_text = report.clarification_question or (
            'Уточните запрос.' if lang == 'ru' else 'Please clarify the request.')
        resp.ui_hints['clarification'] = True
        return resp

    # ranked candidates by evaluation score
    ranked = sorted(
        ((by_id.get(cs.candidate_id), cs) for cs in report.candidate_scores if by_id.get(cs.candidate_id)),
        key=lambda t: t[1].overall_score,
        reverse=True,
    )

    # ── Nothing usable even after escalation → uncertainty/refusal ─────
    if not ranked:
        resp.status = 'uncertain' if live else 'refused'
        resp.answer_text = (
            (_UNCERTAIN_PREFIX_RU if lang == 'ru' else _UNCERTAIN_PREFIX_EN)
            + '\n\n' + '\n\n'.join(c.answer_text[:1500] for c in live[:2])
            if live
            else _REFUSAL_TEMPLATES.get(lang, _REFUSAL_TEMPLATES['en']).format(
                reason='источники не содержали релевантных данных' if lang == 'ru' else 'no relevant data in accessible sources'
            )
        )
        resp.citations = _citations(live)
        resp.sources_summary = _sources_summary(live)
        return resp

    top_cand, top_score = ranked[0]

    # ── Select best (§4.6.2 п.1) ───────────────────────────────────────
    if action == 'select' or len(ranked) == 1:
        chosen = [top_cand]
        resp.status = 'answered' if top_score.overall_score >= settings.min_overall_score else 'uncertain'
    else:
        # ── Merge complementary (§4.6.2 п.2) ───────────────────────────
        chosen = [c for c, s in ranked if s.overall_score >= settings.min_overall_score * 0.8][:3] or [top_cand]
        resp.status = 'partial' if any(c.status == 'partial' for c in chosen) else 'answered'

    blocks: list[str] = []
    for c in chosen:
        header = {'graph_rag': '[граф знаний]', 'hybrid_rag': '[гибридный поиск]',
                  'agentic_rag': '[пошаговый анализ]', 'tool_pipeline': '[внешние источники]',
                  'native_rag': '[документы]'}.get(c.pipeline, f'[{c.pipeline}]')
        body_lines = []
        for cl in c.claims[:6]:
            text = cl.text.strip()
            if not text:
                continue
            if cl.status == 'unsupported' and cl.type == 'fact':
                continue  # §4.5.4 rule: drop unmarked unsupported facts
            elif cl.status in ('inferred', 'partially_supported', 'external_unverified'):
                text += ' ⚠️' if lang == 'ru' else ' [less supported]'
            body_lines.append(f'- {text}')
        if not body_lines:
            body_lines = [c.answer_text[:2000]]
        blocks.append(header + '\n' + '\n'.join(body_lines))

    resp.answer_text = '\n\n'.join(blocks)[:8000]
    if resp.status == 'uncertain':
        resp.answer_text = (_UNCERTAIN_PREFIX_RU if lang == 'ru' else _UNCERTAIN_PREFIX_EN) + '\n\n' + resp.answer_text
    resp.citations = _citations(chosen)
    resp.sources_summary = _sources_summary(chosen)
    resp.warnings = _warnings(report, chosen)
    if policy.required_citations and not resp.citations:
        resp.warnings.append('источники не подтверждены — цитирование недоступно (§4.5.6)')
    resp.ui_hints['confidence_display'] = resp.confidence
    resp.ui_hints['request_id'] = ctx.request_id  # audit handle (§4.6.3)
    return resp
