"""Prompts for the graph layer.

Russian corpora (clinical guidelines, legal medical acts) are indexed and asked
in Russian, so prompts are Russian and require entity names in their original
wording — translated names would break the verbatim-citation property the RAG
context relies on. Output format is JSON because the local models were measured
to follow it (`format: json` grammar makes it deterministic); the tuple format
of upstream nano-graphrag needs a regex parser and degrades badly on small
models.
"""

EXTRACTION_SYSTEM_PROMPT = (
    'Ты извлекаешь граф знаний из фрагментов нормативных и клинических '
    'документов на русском языке.\n'
    'Ответ — строго один JSON-объект, без пояснений и markdown.\n'
    'Схема:\n'
    '{"entities":[{"name":"...","type":"...","description":"..."},...],'
    '"relations":[{"source":"...","target":"...","type":"...","strength":0.0,"evidence":"..."},...]}\n'
    'Правила:\n'
    '- name: точное название сущности как в тексте (именовательный падеж, без лишнего).\n'
    '- type: ровно один из Disease, Drug, Procedure, Anatomy, Symptom, Substance, '
    'Organization, Class. Прочее — Class.\n'
    '- description: 1 предложение из текста, чем является сущность (без выдумывания).\n'
    '- source/target: имена из entities (в том же написании, обязательны).\n'
    '- type связи: 1-3 слова заглавными латиницей через _ (ЛЕЧИТ -> TREATS, '
    'ПРОТИВОПОКАЗАН ПРИ -> CONTRAINDICATED_IN).\n'
    '- strength: уверенность 0.0-1.0, что связь явно следует из текста.\n'
    '- evidence: короткая цитата из фрагмента, подтверждающая связь.\n'
    '- Извлекай только то, что сказано в фрагменте; не дополняй знаниями извне.\n'
    '- Если сущностей нет — верни {"entities":[],"relations":[]}. Отвечай на русском.'
)


def extraction_user_prompt(text: str) -> str:
    return f'Фрагмент документа:\n"""\n{text}\n"""\nВерни JSON.'


ROUTER_SYSTEM_PROMPT = (
    'Реши, нужен ли для вопроса граф знаний (связи между сущностями: что с чем '
    'взаимодействует, противопоказано, применяется вместе, входит в класс) или '
    'достаточно поиска по исходному тексту.\n'
    'Вопросы про факт/формулировку/цитату из документа — VECTOR. Вопросы про '
    'взаимосвязи, сравнение, комбинирование, противопоказания между сущностями — '
    'GRAPH. Если вопрос можно понять только с историей — VECTOR.\n'
    'Ответ — строго JSON: {"route":"GRAPH"} или {"route":"VECTOR"}.'
)


def router_user_prompt(question: str) -> str:
    return f'Вопрос:\n{question}\n\nВерни JSON.'
