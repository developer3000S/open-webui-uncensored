"""Extract entities and relations from the raw text an LLM answered with.

The extractor prompt asks for a single JSON object; small local models wrap it in
markdown fences, trailing prose, or emit one field name per line. Everything that
follows tolerates that noise on purpose: a dropped chunk is a silent quality loss,
while a rescued near-miss is only ever a malformed item filtered below.
"""

import json
import re
from dataclasses import dataclass, field

ENTITY_TYPES = (
    'Disease',
    'Drug',
    'Procedure',
    'Anatomy',
    'Symptom',
    'Substance',
    'Organization',
    'Class',
)

_TYPE_ALIASES = {
    'disease': 'Disease',
    'diagnosis': 'Disease',
    'condition': 'Disease',
    'disorder': 'Disease',
    'болезнь': 'Disease',
    'заболевание': 'Disease',
    'состояние': 'Disease',
    'drug': 'Drug',
    'medication': 'Drug',
    'medicine': 'Drug',
    'antibiotic': 'Drug',
    'pharmaceutical': 'Drug',
    'препарат': 'Drug',
    'лекарство': 'Drug',
    'антибиотик': 'Drug',
    'substance': 'Substance',
    'chemical': 'Substance',
    'вещество': 'Substance',
    'procedure': 'Procedure',
    'treatment': 'Procedure',
    'therapy': 'Procedure',
    'intervention': 'Procedure',
    'процедура': 'Procedure',
    'вмешательство': 'Procedure',
    'метод': 'Procedure',
    'anatomy': 'Anatomy',
    'anatomical': 'Anatomy',
    'body': 'Anatomy',
    'орган': 'Anatomy',
    'анатомия': 'Anatomy',
    'symptom': 'Symptom',
    'sign': 'Symptom',
    'симптом': 'Symptom',
    'признак': 'Symptom',
    'синдром': 'Disease',
    'organization': 'Organization',
    'organisation': 'Organization',
    'institution': 'Organization',
    'организация': 'Organization',
    'учреждение': 'Organization',
    'класс': 'Class',
    'группа': 'Class',
    'категория': 'Class',
    'class': 'Class',
    'group': 'Class',
    'category': 'Class',
    'family': 'Class',
}

MAX_NAME_LEN = 160
MAX_DESC_LEN = 600

# Small local models answer the "UPPER_SNAKE latin" instruction in Russian
# roughly half the time. Without a map, every such edge collapses to RELATED_TO
# and the graph loses exactly the typed information the router sends queries to
# find, so the frequent medical relation verbs are translated here instead.
_RELATION_ALIASES = {
    'вызывает': 'CAUSES',
    'вызван': 'CAUSED_BY',
    'приводит к': 'CAUSES',
    'ведёт к': 'CAUSES',
    'спровоцирован': 'CAUSED_BY',
    'лечит': 'TREATS',
    'лечится': 'TREATED_BY',
    'терапия': 'TREATS',
    'показан': 'INDICATED_FOR',
    'показания': 'INDICATED_FOR',
    'противопоказан': 'CONTRAINDICATED_IN',
    'противопоказание': 'CONTRAINDICATED_IN',
    'нельзя при': 'CONTRAINDICATED_IN',
    'входит в': 'PART_OF',
    'относится к': 'IS_A',
    'является': 'IS_A',
    'группа': 'PART_OF',
    'класс': 'IS_A',
    'содержит': 'CONTAINS',
    'включает': 'CONTAINS',
    'комбинируется с': 'COMBINED_WITH',
    'сочетается с': 'COMBINED_WITH',
    'усиливает': 'POTENTIATES',
    'ослабляет': 'INHIBITS',
    'подавляет': 'INHIBITS',
    'ингибирует': 'INHIBITS',
    'антагонист': 'ANTAGONIZES',
    'взаимодействует с': 'INTERACTS_WITH',
    'связан с': 'ASSOCIATED_WITH',
    'ассоциирован': 'ASSOCIATED_WITH',
    'побочный эффект': 'CAUSES',
    'применяется при': 'INDICATED_FOR',
    'применяется для': 'INDICATED_FOR',
    'используется': 'INDICATED_FOR',
    'назначается': 'INDICATED_FOR',
    'резистентность к': 'RESISTANT_TO',
    'устойчив к': 'RESISTANT_TO',
    'аллергия на': 'ALLERGIC_TO',
    'переносимость': 'TOLERATES',
    'метабол': 'METABOLIZES',
    'связывается с': 'BINDS',
}


def canonical_relation_type(raw: object) -> str:
    """UPPER_SNAKE the relation type — it becomes the Neo4j relationship type.

    Neo4j type names cannot be bound as parameters, so the string goes into the
    query text verbatim; the charset filter below is injection defence, not style.
    """
    text = str(raw or '').strip().lower()
    if text in _RELATION_ALIASES:
        return _RELATION_ALIASES[text]
    token = re.sub(r'[^A-Za-z0-9_ ]', ' ', text)
    token = re.sub(r'[ ]+', '_', token.strip().upper())
    return token[:60] if token else 'RELATED_TO'


@dataclass
class ExtractedEntity:
    name: str
    type: str
    description: str = ''


@dataclass
class ExtractedRelation:
    source: str
    target: str
    type: str
    strength: float = 1.0
    evidence: str = ''


@dataclass
class ExtractionResult:
    entities: list[ExtractedEntity] = field(default_factory=list)
    relations: list[ExtractedRelation] = field(default_factory=list)
    error: str | None = None


def canonical_entity_type(raw: object) -> str:
    """Map a free-form LLM label onto the fixed taxonomy; unknown -> Class.

    The graph query layer filters by type, so an unstable per-document vocabulary
    (Antibiotic vs Drug vs pharmaceutical) would split one concept into nodes.
    """
    token = re.sub(r'[^a-zа-яё]', '', str(raw or '').strip().lower())
    return _TYPE_ALIASES.get(token, 'Class')


def _first_json_object(text: str) -> object | None:
    """Return the first balanced JSON object found in `text`, or None."""
    start = text.find('{')
    while start != -1:
        depth = 0
        in_str = False
        escape = False
        for idx in range(start, len(text)):
            ch = text[idx]
            if in_str:
                if escape:
                    escape = False
                elif ch == '\\':
                    escape = True
                elif ch == '"':
                    in_str = False
                continue
            if ch == '"':
                in_str = True
            elif ch == '{':
                depth += 1
            elif ch == '}':
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[start : idx + 1])
                    except json.JSONDecodeError:
                        break
        start = text.find('{', start + 1)
    return None


def _clean_name(raw: object) -> str:
    name = re.sub(r'\s+', ' ', str(raw or '')).strip(' .;:,-')
    if not name or len(name) < 2 or len(name) > MAX_NAME_LEN:
        return ''
    return name


def parse_extraction(text: str) -> ExtractionResult:
    """Parse one LLM answer into validated entities and relations."""
    if not text or not text.strip():
        return ExtractionResult(error='empty response')

    data = _first_json_object(text)
    if data is None:
        return ExtractionResult(error='no JSON object in response')
    if not isinstance(data, dict):
        return ExtractionResult(error='JSON root is not an object')

    raw_entities = data.get('entities') or data.get('Nodes') or []
    raw_relations = data.get('relations') or data.get('Relationships') or []
    if not isinstance(raw_entities, list):
        raw_entities = []
    if not isinstance(raw_relations, list):
        raw_relations = []

    entities: list[ExtractedEntity] = []
    seen: set[str] = set()
    for item in raw_entities:
        if not isinstance(item, dict):
            continue
        name = _clean_name(item.get('name') or item.get('entity') or item.get('id'))
        if not name or name.lower() in seen:
            continue
        seen.add(name.lower())
        desc = re.sub(r'\s+', ' ', str(item.get('description') or '')).strip()
        entities.append(
            ExtractedEntity(
                name=name,
                type=canonical_entity_type(item.get('type')),
                description=desc[:MAX_DESC_LEN],
            )
        )

    names = {e.name.lower(): e.name for e in entities}
    relations: list[ExtractedRelation] = []
    rel_seen: set[tuple] = set()
    for item in raw_relations:
        if not isinstance(item, dict):
            continue
        src = _clean_name(item.get('source') or item.get('src'))
        tgt = _clean_name(item.get('target') or item.get('dst'))
        # Relations referencing dropped entities would add orphan nodes that no
        # chunk can vouch for; the entity list already holds what was extracted.
        if src.lower() in names:
            src = names[src.lower()]
        if tgt.lower() in names:
            tgt = names[tgt.lower()]
        if not src or not tgt or src == tgt:
            continue
        if src not in names.values() or tgt not in names.values():
            continue
        rtype = canonical_relation_type(item.get('type') or item.get('relationship'))
        try:
            strength = float(item.get('strength', 1.0))
        except (TypeError, ValueError):
            strength = 1.0
        strength = min(max(strength, 0.0), 1.0)
        key = (src.lower(), tgt.lower(), rtype)
        if key in rel_seen:
            continue
        rel_seen.add(key)
        evidence = re.sub(r'\s+', ' ', str(item.get('evidence') or '')).strip()[:MAX_DESC_LEN]
        relations.append(ExtractedRelation(src, tgt, rtype, strength, evidence))

    if not entities and not relations:
        return ExtractionResult(error='no usable items in JSON')
    return ExtractionResult(entities=entities, relations=relations)
