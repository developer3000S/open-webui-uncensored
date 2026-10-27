"""Query router between vector RAG and GraphRAG (the orchestrator).

Routing must be free: every LLM call on the query path costs seconds on a
CPU-only model, and a wrong extra hop is worse than a missing one, because
plain RAG already runs and its chunks stay in the context. So the decision is
made lexically — a Russian relation-cue vocabulary, two or more cues (or one
cue in a longer question) means relationships are being asked about. The
keyword heuristic from the Medical-Graph-RAG draft was kept in spirit and fixed
in accuracy: its list included «какой», which fires on almost any question.
"""

import logging
import os
import re

log = logging.getLogger(__name__)


# Read live, not frozen at import: this module is pure (unit-tested without the
# app config) and the switch must react to an admin edit without a restart.
def graph_enabled() -> bool:
    return os.getenv('GRAPHRAG_ENABLED', 'False').lower() == 'true'


def graph_mode() -> str:
    return os.getenv('GRAPHRAG_MODE', 'auto').strip().lower()


# The regex alternation picks the first matching branch, so cues are sorted
# longest-first: «взаимодействие» must not be counted twice via «связи».
_RELATION_CUES = (
    'взаимодействие',
    'взаимодейств',
    'несовместим',
    'противопоказ',
    'сочетаем',
    'комбинир',
    'совместим',
    'влияние',
    'влияет',
    'усилива',
    'ослабля',
    'подавля',
    'ингибир',
    'антагонис',
    'агонис',
    'побочн',
    'нежелательн',
    'входит',
    'относит',
    'связан',
    'связи',
    'цепочк',
    'классифиц',
    'групп',
    'показан',
    'эффект',
    'причин',
    'вызыва',
    'провоцир',
    'ведёт к',
    'приводит к',
    'между',
    'с чем',
    'зависим',
    'путь',
    'маршрут',
    'граф',
    'узел',
)

_CUE_RE = re.compile('|'.join(re.escape(c) for c in sorted(_RELATION_CUES, key=len, reverse=True)))


def relation_signal(query: str) -> int:
    """Number of distinct relation cues in the query (case-insensitive)."""
    text = query.lower()
    return len(set(m.group(0) for m in _CUE_RE.finditer(text)))


def should_use_graph(query: str) -> bool:
    """Decide whether the query needs graph traversal in addition to RAG."""
    if not graph_enabled():
        return False
    mode = graph_mode()
    if mode == 'never':
        return False
    if mode == 'always':
        return True
    if not query or not query.strip():
        return False

    score = relation_signal(query)
    if score >= 2:
        return True
    if score == 1 and len(query.split()) >= 4:
        return True
    return False
