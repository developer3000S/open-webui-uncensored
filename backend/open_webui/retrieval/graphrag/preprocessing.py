"""Preprocessing Layer (ТЗ §4.1): raw request -> QueryContext.

Everything here is deterministic and cheap — no LLM calls on the query path
(the deployment runs CPU models; a wrong extra hop costs more than a missing
one, per the routing doctrine in orchestrator.py). The layer implements the
mandatory functions of §4.1.2: normalization, language detection, PII and
safety screening, basic feature extraction, anaphora resolution from chat
history, cache keying, token bounding, and request/trace identity.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata

from open_webui.retrieval.graphrag.models import QueryContext, QueryFeatures, UserContext

# ── Normalization (§4.1.2 п.3) ─────────────────────────────────────────

_INVALID_UNICODE_RE = re.compile(r'[\ufeff\ufffe\uffff\x00-\x08\x0b\x0c\x0e-\x1f\x7f]')


def normalize_text(raw: str) -> str:
    """Strip control junk, unify whitespace/newlines, NFKC-normalize."""
    if not raw:
        return ''
    text = _INVALID_UNICODE_RE.sub('', raw)
    text = unicodedata.normalize('NFKC', text)
    # Keep line structure (paragraphs matter for instruction/question split),
    # but collapse runs of spaces/tabs and stray blank lines.
    text = re.sub(r'[ \t\u00a0]+', ' ', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


# ── Language detection (§4.1.2 п.4) ────────────────────────────────────

_CYRILLIC_RE = re.compile(r'[а-яёА-ЯЁ]')
_LATIN_RE = re.compile(r'[a-zA-Z]')


def detect_language(text: str) -> str:
    """Minimal ru/en discriminator (ТЗ §5.6 default languages)."""
    cyr = len(_CYRILLIC_RE.findall(text or ''))
    lat = len(_LATIN_RE.findall(text or ''))
    if cyr == 0 and lat == 0:
        return 'en'
    return 'ru' if cyr >= lat else 'en'


# ── PII / sensitive data flags (§4.1.2 п.5) ────────────────────────────

_PII_PATTERNS: dict[str, re.Pattern] = {
    'email': re.compile(r'[\w.+-]+@[\w-]+\.[\w.-]+'),
    'phone': re.compile(r'(?:\+?\d[\d\s().-]{8,}\d)'),
    'credit_card': re.compile(r'\b(?:\d[ -]*?){13,19}\b'),
    'passport_ru': re.compile(r'\b\d{2}[\s-]?\d{6}\b(?!\s*(?:год|г\.))'),
    'sniils': re.compile(r'\b\d{3}-\d{3}-\d{3}\s?\d{2}\b'),
    'secret_token': re.compile(
        r'(?i)\b(?:api[_-]?key|secret|token|password|passwd|authorization|bearer)\b\s*[:=]\s*\S+'
    ),
}


def detect_pii(text: str) -> list[str]:
    flags = []
    for name, pattern in _PII_PATTERNS.items():
        if pattern.search(text or ''):
            flags.append(name)
    return flags


# ── Primary safety screen (§4.1.2 п.6, §6.3) ───────────────────────────

_INJECTION_RU_EN = [
    # prompt-leak attempts
    r'(?i)(reveal|show|print|repeat|output|передай|покажи|раскрой|выведи|напиши)\s+(me\s+)?(your\s+)?'
    r'(hidden\s+)?(system\s+)?(prompt|instructions?|инструкци|системн\w*\s+промпт|промпт)',
    # policy-override attempts
    r'(?i)ignore\s+(all\s+|any\s+)?(previous|prior|above|earlier)\s+(instructions?|rules?|policy|политик)',
    r'(?i)забудь\s+(все|все\s+предыдущие|прежние)\s+(инструкц|правила|политик)',
    r'(?i)you\s+are\s+now\s+(in\s+)?(developer|dan|jailbreak|unrestricted)\s*mode',
    r'(?i)(act|pretend)\s+as\s+if\s+you\s+have\s+no\s+(restrictions|rules|ограничен)',
    # ACL-bypass attempts
    r'(?i)(bypass|circumvent|obtain|expose)\s+(the\s+)?(access\s+control|acl|permissions|права\s+доступа)',
    r'(?i)обойти\s+(ограничен|политик|доступ|фильтр)',
    # forbidden-action requests
    r'(?i)(how\s+to\s+)?(make|build|synthesize)\s+(a\s+)?(bomb|weapon|malware|exploit|вирус|взрывчат)',
]

_INJECTION_LABELS = [
    'prompt_leakage',
    'instruction_override',
    'instruction_override',
    'persona_hijack',
    'persona_hijack',
    'acl_bypass',
    'acl_bypass',
    'forbidden_action',
]

_INJECTION_RE = [re.compile(p) for p in _INJECTION_RU_EN]


def detect_safety_flags(text: str) -> list[str]:
    flags = []
    low = text or ''
    for label, pattern in zip(_INJECTION_LABELS, _INJECTION_RE):
        if pattern.search(low):
            flags.append(label)
    return sorted(set(flags))


# ── Basic features (§4.1.2 п.7) + recommended heuristics (§4.1.3) ──────

_QUESTION_MARK_RE = re.compile(r'[?？]|\b(как|что|почему|зачем|когда|где|кто|какой|какие|ли)\b', re.I)
_NEGATION_RE = re.compile(r'(?i)\b(no|not|never|without|нет|не|ни|без)\b')
_TEMPORAL_RE = re.compile(
    r'(?i)\b(now|today|yesterday|recent(ly)?|current|latest|this|last|next)\b'
    r'|\b(сейчас|сегодня|вчера|недавно|последн\w*|текущ\w*|актуальн\w*|в\s+\d{4}\s+году|этого\s+года)'
)
_NUMERIC_RE = re.compile(r'\d+(\.\d+)?\s*(%|₽|\$|€|руб|долл|евро|кг|мг|мл|см|км|лет|годов?|дней|часов|минут)?')
_PROPER_NAME_RE = re.compile(r'\b[A-ZА-ЯЁ][a-zа-яё]{2,}(?:\s+[A-ZА-ЯЁ][a-zа-яё]{2,})?\b')
_ANAPHORA_RE = re.compile(
    r'(?i)\b(it|this|that|they|them|he|she|his|her|its|above|aforementioned|former|latter)\b'
    r'|\b(это|этот|эта|эти|его|её|они|их|вышеуказанн\w*|указанный|выше|первый|второй|последний)\b'
)
_MULTI_Q_RE = re.compile(r'[?.!]\s*[A-ZА-ЯЁ].{6,}[?？]')
_IMPERATIVE_INSTRUCTION_RE = re.compile(
    r'(?i)^(?:please\s+)?(?:summarize|compare|list|translate|calculate|explain|оформи|сравни|переведи|посчитай|составь)\b'
)


def extract_features(query: str, history: list[dict] | None = None) -> QueryFeatures:
    words = (query or '').split()
    return QueryFeatures(
        length_chars=len(query or ''),
        word_count=len(words),
        is_question=bool(_QUESTION_MARK_RE.search(query or '')),
        has_negation=bool(_NEGATION_RE.search(query or '')),
        has_temporal_expression=bool(_TEMPORAL_RE.search(query or '')),
        has_numeric=bool(_NUMERIC_RE.search(query or '')),
        has_proper_names=bool(_PROPER_NAME_RE.search(query or '')),
        has_anaphoric_reference=bool(_ANAPHORA_RE.search(query or '')),
        instruction_only=bool(_IMPERATIVE_INSTRUCTION_RE.match((query or '').strip())) and '?' not in (query or ''),
    )


# ── Lightweight entity candidates (§4.1.3) ─────────────────────────────


def extract_entity_candidates(query: str) -> list[str]:
    """Capitalized spans + quoted terms — cheap stand-in for an NER model."""
    found: list[str] = []
    for m in _PROPER_NAME_RE.finditer(query or ''):
        span = m.group(0).strip()
        if span.lower() not in {'и', 'в', 'на', 'the', 'a'}:
            found.append(span)
    for m in re.finditer(r'[«"“]([^»"”]{3,60})[»"”]', query or ''):
        found.append(m.group(1).strip())
    seen, out = set(), []
    for e in found:
        k = e.lower()
        if k not in seen:
            seen.add(k)
            out.append(e)
    return out[:16]


# ── Anaphora resolution (§4.1.2 п.8) ───────────────────────────────────


def resolve_anaphora(query: str, history: list[dict] | None) -> tuple[str, bool]:
    """Substitute the most recent assistant-topic when the query references it.

    Deliberately conservative: only rewrites when the current message is short
    and referential, so unrelated pronouns inside long questions stay put.
    """
    if not history:
        return query, False
    last_user = None
    for msg in reversed(history):
        if isinstance(msg, dict) and msg.get('role') == 'user':
            content = msg.get('content')
            if isinstance(content, str) and content.strip():
                last_user = content.strip()
                break
    if not last_user:
        return query, False
    words = (query or '').split()
    if len(words) <= 8 and _ANAPHORA_RE.search(query or ''):
        topic_tail = ' '.join(last_user.split()[:12])
        resolved = f'{query} (контекст предыдущего вопроса: {topic_tail})'
        return resolved, True
    return query, False


# ── Token counting (§4.1.2 п.11) ───────────────────────────────────────

_MAX_CONTEXT_TOKENS_DEFAULT = 8192


def estimate_tokens(text: str) -> int:
    """Heuristic ~4 chars/token; good enough for budget guards, no tokenizer dep."""
    return max(1, len(text or '') // 4) if text else 0


def bound_context(query: str, max_tokens: int = _MAX_CONTEXT_TOKENS_DEFAULT) -> str:
    limit = max(64, max_tokens * 4)
    return (query or '')[:limit]


# ── Cache key (§4.1.2 п.10) ────────────────────────────────────────────


def build_cache_key(normalized_query: str, tenant_id: str | None, collection_ids: list[str]) -> str:
    """Isolated per tenant AND per permission set (§6.2): same text under a
    different KB scope must never share a cache entry."""
    parts = '|'.join(sorted(collection_ids or []))
    digest = hashlib.sha256(f'{tenant_id or "-"}::{parts}::{normalized_query}'.encode()).hexdigest()
    return f'orch:q:{digest[:32]}'


# ── Entry point ────────────────────────────────────────────────────────


def preprocess_query(
    raw_query: str,
    *,
    user: dict | None = None,
    history: list[dict] | None = None,
    session_id: str | None = None,
    attachments: list[dict] | None = None,
    items: list[dict] | None = None,
    max_context_tokens: int = _MAX_CONTEXT_TOKENS_DEFAULT,
) -> QueryContext:
    """Run the full §4.1.2 pipeline and produce the QueryContext contract."""
    normalized = normalize_text(raw_query)
    resolved, was_resolved = resolve_anaphora(normalized, history)
    resolved = bound_context(resolved, max_context_tokens)

    language = detect_language(resolved)
    pii_flags = detect_pii(resolved)
    safety_flags = detect_safety_flags(resolved)
    features = extract_features(resolved, history)
    entities = extract_entity_candidates(resolved)

    user_ctx = UserContext(
        user_id=(user or {}).get('id'),
        tenant_id=(user or {}).get('tenant_id') or (user or {}).get('id'),
        role=(user or {}).get('role'),
        roles=[(user or {}).get('role')] if (user or {}).get('role') else [],
        permissions=list((user or {}).get('permissions') or []),
    )

    collection_ids = [str(i.get('id')) for i in (items or []) if isinstance(i, dict) and i.get('id')]
    cache_key = build_cache_key(resolved, user_ctx.tenant_id, collection_ids)

    ctx = QueryContext(
        raw_query=raw_query or '',
        normalized_query=resolved,
        language=language,
        session_id=session_id,
        conversation_history=list(history or []),
        user_context=user_ctx,
        attachments=list(attachments or []),
        detected_entities=entities,
        pii_flags=pii_flags,
        safety_flags=safety_flags,
        cache_key=cache_key,
        token_count=estimate_tokens(resolved),
        features=features,
        items=list(items or []),
    )
    if was_resolved:
        ctx.features.has_anaphoric_reference = True
    return ctx
