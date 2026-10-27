"""Query rewriting for the retrieval legs of the orchestrator (rec §2.2).

Retrieval quality is bounded by how well the query string matches the indexed
chunks. This module performs cheap, deterministic rewrites *before* a pipeline
task hits the vector/BM25 index — no LLM hop, in line with the CPU doctrine
for routing-time work (§15.1 latency budget):

* compound decomposition — "сравни X и Y", "что такое X и Y" split into one
  sub-query per subject so each entity gets its own retrieval pass (the pool
  evaluator then merges the evidence);
* de-contextualization — follow-up anaphora ("он", "это", "первый вариант")
  are already resolved against history in preprocessing; here we additionally
  append the dominant history topic when the current query is very short;
* multi-hop chaining markers — "почему/следовательно/причина" queries get a
  causal-phrased variant appended, which retrieves explanation chunks that a
  bare keyword query misses;
* HyDE-lite (optional, ORCH_HYDE=off by default) — instead of generating a
  hypothetical document with an LLM, expand the query with high-DF terms from
  the entity lexicon of the graph layer when available.

`rewrite_variants()` returns the list of query strings to run; adapters dedupe
results across variants inside the shared candidate pool (§4.4).
"""

from __future__ import annotations

import logging
import os
import re

log = logging.getLogger(__name__)

# Russian + English contrast/conjunction patterns that mark a compound query.
_COMPARISON_RE = re.compile(
    r'\b(сравн\w*|чем отличается|отличия|versus|vs\.?|compare|разниц\w+)\b',
    re.IGNORECASE,
)
_AND_SPLIT_RE = re.compile(
    r'\s+(?:и|а|или|також|as well as|and|or)\s+',
    re.IGNORECASE,
)
_CAUSAL_RE = re.compile(
    r'\b(почему|зачем|причин\w*|следств\w*|из-за|why|because|cause[sd]?|reason)\b',
    re.IGNORECASE,
)
_MULTI_ENTITY_RE = re.compile(
    # quoted names or capitalized latin runs — crude but language-agnostic
    r'("[^"]{3,}"|«[^»]{3,}»|[A-ZА-ЯЁ][a-zа-яё]{2,}(?:\s+[A-ZА-ЯЁ][a-zа-яё]{2,}){0,3})',
)
_STOPWORDS = {
    'что', 'как', 'какой', 'какие', 'такое', 'такой', 'это', 'есть', 'было',
    'для', 'него', 'неё', 'них', 'сам', 'про', 'the', 'what', 'how', 'does',
    'please', 'tell', 'about',
}


def _clean_fragment(text: str) -> str:
    text = re.sub(r'[?？!.,;:]+$', '', text.strip())
    words = [w for w in text.split() if w.lower() not in _STOPWORDS]
    return ' '.join(words).strip()


def decompose_compound(query: str, intent: str | None = None) -> list[str]:
    """Split comparison/multi-entity queries into per-subject sub-queries."""
    variants: list[str] = []
    entities = [m.group(0).strip(' «»"') for m in _MULTI_ENTITY_RE.finditer(query)]
    # Deduplicate preserving order, drop trivially short captures.
    seen: set[str] = set()
    entities = [e for e in entities if not (e.lower() in seen or seen.add(e.lower())) and len(e) >= 3]

    is_comparison = bool(_COMPARISON_RE.search(query)) or intent == 'comparison'
    if is_comparison and len(entities) >= 2:
        # Each subject queried on its own keeps retrieval precision; the raw
        # comparison phrasing itself is kept too (definitions often live in
        # comparison sections of docs).
        variants.extend(entities[:4])
        variants.append(query)
        return variants

    # Generic "X и Y" conjunction over long tails: try splitting the object
    # clause when both sides look like independent noun phrases.
    if len(entities) >= 2 and _AND_SPLIT_RE.search(query):
        parts = [p for p in _AND_SPLIT_RE.split(query) if len(_clean_fragment(p)) >= 8]
        if 2 <= len(parts) <= 4:
            variants.extend(_clean_fragment(p) for p in parts)
            variants.append(query)
    return variants


def causal_variant(query: str) -> list[str]:
    """Append an explanation-shaped variant for causal intents."""
    if _CAUSAL_RE.search(query):
        return [f'{query} причина обоснование объяснение']
    return []


def topic_pinned_variant(query: str, history: list[dict] | None) -> list[str]:
    """Short follow-ups inherit the dominant topic of the previous turn."""
    if len(query.split()) > 4 or not history:
        return []
    last_user = next((h.get('content', '') for h in reversed(history) if h.get('role') == 'user'), '')
    if not last_user:
        return []
    topic_words = [w for w in re.findall(r'[A-Za-zА-Яа-яЁё]{4,}', last_user)][:6]
    if not topic_words:
        return []
    return [f'{query} {" ".join(topic_words)}']


def hyde_lite(query: str, entity_lexicon: list[str] | None) -> list[str]:
    """ORCH_HYDE: expand with matching known entities (graph lexicon proxy)."""
    if os.getenv('ORCH_HYDE', '').strip().lower() not in ('1', 'true', 'yes', 'on'):
        return []
    if not entity_lexicon:
        return []
    ql = query.lower()
    hits = [e for e in entity_lexicon if e and e.lower() in ql][:5]
    if not hits or len(hits) == sum(1 for e in hits if True) and all(h.lower() in ql for h in hits):
        # All expansions already present verbatim in the query — nothing to add.
        return []
    return [' '.join([query] + [h for h in hits if h.lower() not in ql])]


def rewrite_variants(
    query: str,
    *,
    intent: str | None = None,
    history: list[dict] | None = None,
    entity_lexicon: list[str] | None = None,
    max_variants: int = 4,
) -> list[str]:
    """Ordered, deduplicated list of retrieval queries (primary first)."""
    out: list[str] = [query]
    for group in (
        decompose_compound(query, intent),
        causal_variant(query),
        topic_pinned_variant(query, history),
        hyde_lite(query, entity_lexicon),
    ):
        for v in group:
            v = (v or '').strip()
            if v and v.lower() not in {o.lower() for o in out}:
                out.append(v)
    return out[:max_variants]
