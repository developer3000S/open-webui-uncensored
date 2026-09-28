"""Query Understanding (ТЗ §4.2.3): intent, complexity and evidence needs.

Classification is lexical-probabilistic: cue-vocabulary scores per intent are
combined with the structural features from preprocessing, the winning class
carries its margin as confidence (§4.2.3 п.10). No LLM call — the router must
stay under ~1 ms so the escalation ladder of §2.2 never pays a model hop just
to decide whether to pay one. The vocabulary covers both Russian and English
because the deployment answers in both (§5.6).
"""

from __future__ import annotations

import re

from open_webui.retrieval.graphrag.models import QueryAnalysis
from open_webui.retrieval.graphrag.orchestrator import relation_signal

# Cue vocabularies per intent (ТЗ §10.1 "Признаки" column, ru+en).
_INTENT_CUES: dict[str, list[str]] = {
    'definition': [
        'что такое', 'определени', 'дай определение', 'кто такой', 'что значит', 'что означает',
        'what is', 'what does', 'define', 'definition', 'meaning of', 'means',
    ],
    'procedural': [
        'как выполнить', 'как сделать', 'как настроить', 'как установить', 'пошагово', 'инструкци',
        'процедура', 'алгоритм действий', 'steps', 'how to', 'how do i', 'setup', 'install', 'guide',
    ],
    'comparative': [
        'чем отличается', 'отличи', 'сравн', 'лучше', 'хуже', 'против', 'альтернатив', 'версии',
        'difference', 'compare', 'versus', 'vs', 'better', 'worse', 'trade-off',
    ],
    'causal': [
        'почему', 'причин', 'влияет', 'приводит к', 'ведёт к', 'из-за', 'благодаря', 'провоцир',
        'следстви', 'вызыва', 'why', 'cause', 'causes', 'leads to', 'because', 'due to', 'impact',
    ],
    'temporal': [
        'когда', 'дата', 'срок', 'до', 'после', 'истори', 'хронологи', 'текущ', 'актуальн',
        'when', 'date', 'deadline', 'timeline', 'history', 'before', 'after', 'current', 'latest',
    ],
    'multi_hop': [
        'и затем', 'после этого', 'сначала', 'потом', 'кроме того', 'а также', 'сколько всего',
        'then', 'after that', 'furthermore', 'in addition', 'chain',
    ],
    'graph_relation': [
        'связан', 'связи', 'между', 'зависим', 'взаимодейств', 'классифиц', 'иерархи', 'подчиняется',
        'относит', 'входит в', 'состоит из', 'родствен', 'путь', 'сосед',
        'related to', 'relationship', 'depends on', 'interact', 'hierarchy', 'belongs to', 'consists of',
    ],
    'summary': [
        'кратко', 'резюме', 'сводка', 'обзор', 'основные темы', 'общая картина', 'пересказ',
        'summarize', 'summary', 'overview', 'recap', 'main topics', 'big picture',
    ],
    'analysis': [
        'проанализируй', 'анализ', 'оцени', 'исследуй', 'выяви', 'закономерност', '趋势',
        'analyze', 'analysis', 'evaluate', 'assess', 'investigate', 'trends',
    ],
    'calculation': [
        'посчитай', 'рассчитай', 'вычисли', 'сколько будет', 'формула', 'сумма', 'процент', 'среднее',
        'calculate', 'compute', 'how much is', 'formula', 'average', 'total', 'sum', 'percentage',
    ],
    'external_lookup': [
        'новости', 'курс', 'цена', 'погода', 'сейчас', 'сегодня', 'актуальный курс', 'в интернете',
        'news', 'stock price', 'weather', 'exchange rate', 'nowadays', 'on the web', 'look up online',
    ],
    'conversational': [
        'спасибо', 'благодарю', 'привет', 'здравствуй', 'как дела', 'пожалуйста', 'до свидания',
        'hello', 'hi', 'thanks', 'thank you', 'goodbye', 'how are you',
    ],
}

_UNSAFE_RE = re.compile(
    r'(?i)(bomb|weapon|exploit|malware|hack into|взлом|вирус|оружи|взрывчат|наркот.*производ)'
)

_DOMAIN_CUES: dict[str, list[str]] = {
    'медицина': ['болезн', 'симптом', 'лекарств', 'препарат', 'доза', 'диагноз', 'врач', 'лечени',
                 'disease', 'symptom', 'drug', 'dose', 'diagnosis', 'treatment', 'medicine'],
    'право': ['закон', 'статья', 'договор', 'правил', 'суд', 'юриdic', 'law', 'legal', 'contract',
              'regulation', 'clause', 'court'],
    'финансы': ['бюджет', 'налог', 'инвестиц', 'акци', 'отчётность', 'budget', 'tax', 'invest',
                'finance', 'equity', 'revenue'],
    'технический': ['сервер', 'api', 'база данных', 'конфигурац', 'deploy', 'server', 'database',
                    'config', 'build', 'kubernetes', 'docker'],
}

_MULTI_QUESTION_RE = re.compile(r'[?？].{10,}[?？]', re.S)
_SUBORDINATE_CHAIN_RE = re.compile(
    r'(?i)\b(которые?|которая|которые|после того как|если тогд|и при этом|а тот)\b'
    r'|\b(which|that (?:is|are)|if then|and then the)\b'
)


def _score_intents(text: str) -> dict[str, float]:
    low = text.lower()
    scores: dict[str, float] = {}
    for intent, cues in _INTENT_CUES.items():
        hits = 0.0
        for cue in cues:
            if cue in low:
                # longer cues are stronger evidence than incidental word hits
                hits += 1.0 + min(len(cue), 20) / 40.0
        if hits:
            scores[intent] = round(min(hits / 3.0, 1.0), 3)
    return scores


def detect_domain(text: str) -> str | None:
    low = (text or '').lower()
    best, best_hits = None, 0
    for domain, cues in _DOMAIN_CUES.items():
        hits = sum(1 for c in cues if c in low)
        if hits > best_hits:
            best, best_hits = domain, hits
    return best if best_hits >= 1 else None


def analyze_query(query_context) -> QueryAnalysis:
    """Classify the normalized query into the §4.2.3 QueryAnalysis contract."""
    text = query_context.normalized_query or query_context.raw_query
    feats = query_context.features
    scores = _score_intents(text)

    unsafe = bool(_UNSAFE_RE.search(text)) or 'forbidden_action' in (query_context.safety_flags or [])
    if unsafe:
        scores['unsafe'] = 1.0

    # Ambiguity: referential queries with no history, or several equally-scored
    # intents, or an instruction without a question target.
    top = sorted(scores.items(), key=lambda kv: -kv[1])
    ambiguity = 0.0
    if len(top) >= 2 and top[0][1] > 0 and abs(top[0][1] - top[1][1]) < 0.15:
        ambiguity = 0.5
    if feats.has_anaphoric_reference and not query_context.conversation_history:
        ambiguity = max(ambiguity, 0.7)
    if not feats.is_question and not scores:
        ambiguity = max(ambiguity, 0.3)
    if (text or '').strip() and len((text or '').split()) <= 2 and not scores:
        ambiguity = max(ambiguity, 0.6)
    if scores:
        scores['ambiguous'] = round(max(scores.get('ambiguous', 0.0), ambiguity), 3)

    # Pick intent: unsafe wins outright; otherwise highest cue score; fallback
    # by structure (question -> simple_fact, statement -> conversational).
    if unsafe:
        intent = 'unsafe'
    elif top:
        intent = top[0][0]
    elif feats.is_question:
        intent = 'simple_fact'
    else:
        intent = 'conversational'

    graph_cues = relation_signal(text)
    multi_q = bool(_MULTI_QUESTION_RE.search(text)) or bool(_SUBORDINATE_CHAIN_RE.search(text))

    requires_external = intent == 'external_lookup' or (
        feats.has_temporal_expression and any(w in text.lower() for w in ('сейчас', 'сегодня', 'now', 'today', 'новост', 'news'))
    )
    requires_calculation = intent == 'calculation' or (feats.has_numeric and re.search(r'(?i)(посчитай|рассчитай|сколько будет|calculate|compute)', text))
    requires_graph = intent in ('graph_relation', 'causal') or graph_cues >= 2 or (
        intent == 'comparative' and graph_cues >= 1
    )
    requires_multi_step = intent in ('multi_hop', 'analysis', 'calculation') or (multi_q and intent != 'conversational')
    requires_comparison = intent == 'comparative'

    # Complexity ladder feeds the escalation policy (§2.2).
    weight = {
        'conversational': 0, 'simple_fact': 0, 'definition': 0, 'temporal': 1,
        'procedural': 1, 'summary': 1, 'comparative': 2, 'causal': 2, 'graph_relation': 2,
        'analysis': 2, 'calculation': 2, 'external_lookup': 2, 'multi_hop': 3, 'unsupported': 3,
        'ambiguous': 2, 'unsafe': 3,
    }.get(intent, 1)
    extra = sum([requires_graph, requires_multi_step, requires_calculation, requires_external, multi_q])
    total = weight + extra
    complexity = 'low' if total <= 1 else 'medium' if total <= 3 else 'high' if total <= 5 else 'very_high'

    # Answerability prior: how likely an internal corpus can answer at all.
    answerability = 1.0
    if intent == 'external_lookup':
        answerability = 0.4
    if intent == 'conversational':
        answerability = 0.9
    if intent == 'unsafe':
        answerability = 0.0
    if ambiguity >= 0.6:
        answerability = min(answerability, 0.5)

    safety_risk = 0.0
    if unsafe:
        safety_risk = 1.0
    elif query_context.pii_flags:
        safety_risk = 0.4
    if detect_domain(text) in ('медицина', 'право', 'финансы'):
        safety_risk = max(safety_risk, 0.55)

    clarification_recommended = ambiguity >= 0.6 or intent == 'ambiguous'

    temporal = re.findall(
        r'(?i)\b(now|today|yesterday|last\s+\w+|next\s+\w+|in\s+\d{4}|сейчас|сегодня|вчера|последн\w+|в\s+\d{4}\s+году)\b',
        text or '',
    )

    evidence: list[str] = []
    if requires_graph:
        evidence.append('графовые связи между сущностями')
    if requires_calculation:
        evidence.append('числовые данные и формулы')
    if requires_external:
        evidence.append('внешние актуальные источники')
    if requires_comparison:
        evidence.append('несколько сопоставимых документов')
    if intent in ('procedural', 'definition', 'simple_fact'):
        evidence.append('точный фрагмент документации')

    return QueryAnalysis(
        intent=intent,
        domain=detect_domain(text),
        complexity=complexity,
        requires_exact_match=intent in ('definition', 'procedural', 'simple_fact'),
        requires_semantic_search=intent not in ('conversational', 'calculation'),
        requires_graph=bool(requires_graph),
        requires_multi_step=bool(requires_multi_step),
        requires_external_data=bool(requires_external),
        requires_calculation=bool(requires_calculation),
        requires_comparison=bool(requires_comparison),
        ambiguity_score=round(min(ambiguity, 1.0), 3),
        answerability_score=round(answerability, 3),
        safety_risk_score=round(safety_risk, 3),
        clarification_recommended=clarification_recommended,
        entities=list(query_context.detected_entities),
        relations=[],
        temporal_expressions=[t[0] if isinstance(t, tuple) else t for t in temporal][:8],
        evidence_hypotheses=evidence,
        intent_confidences=scores,
    )
