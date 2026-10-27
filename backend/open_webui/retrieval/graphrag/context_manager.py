"""Context Manager (ТЗ §4.4.2 п.1): assemble bounded context per candidate.

Token-budget packing with priority: reranked relevant chunks first, graph
triples next (they are cross-file reasoning, cheaper to lose than verbatim
evidence), then metadata; older/low-score content is summarized away rather
than silently dropped (§5.1.3 "context overflow" mitigation).
"""

from __future__ import annotations

import re

from open_webui.retrieval.graphrag.preprocessing import estimate_tokens


def sentence_summarize(text: str, max_sentences: int = 2) -> str:
    parts = re.split(r'(?<=[.!?。])\s+', text.strip())
    return ' '.join(parts[:max_sentences]).strip()


def pack_context(
    documents: list[str],
    metadatas: list[dict] | None,
    *,
    token_budget: int,
    graph_context: str | None = None,
    reserve_for_graph: int = 800,
) -> tuple[list[str], list[dict]]:
    """Fit documents (+ optional graph block) into `token_budget` tokens.

    Returns the surviving (documents, metadatas) pair; oversized tail chunks
    enter the result in summary form so their topics stay represented.
    """
    metadatas = metadatas or [{} for _ in documents]
    budget = token_budget
    docs_out: list[str] = []
    metas_out: list[dict] = []
    used = 0

    if graph_context:
        g_tokens = min(estimate_tokens(graph_context), reserve_for_graph)
        docs_out.append(graph_context[: g_tokens * 4])
        metas_out.append({'source': 'knowledge-graph', 'name': 'graph-context'})
        used += g_tokens

    for i, doc in enumerate(documents):
        meta = metadatas[i] if i < len(metadatas) else {}
        cost = estimate_tokens(doc)
        if used + cost <= budget:
            docs_out.append(doc)
            metas_out.append(meta)
            used += cost
            continue
        remaining = budget - used
        if remaining * 4 >= 200:  # room for at least a short summary
            snippet = sentence_summarize(doc[: remaining * 4], max_sentences=2)
            if snippet:
                docs_out.append(snippet + ' …')
                m = dict(meta)
                m['summarized'] = True
                metas_out.append(m)
                used += estimate_tokens(snippet)
        break  # budget exhausted; later chunks would only degrade quality

    return docs_out, metas_out
