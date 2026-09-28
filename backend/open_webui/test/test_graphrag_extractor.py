"""Unit tests for the pure parts of the graph layer (no Neo4j, no LLM).

Run: python3 backend/open_webui/test/test_graphrag_extractor.py
"""

import sys
import unittest
import unittest.mock
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[2]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from open_webui.retrieval.graphrag.extractor import (
    canonical_entity_type,
    canonical_relation_type,
    parse_extraction,
)
from open_webui.retrieval.graphrag.orchestrator import relation_signal, should_use_graph
from open_webui.retrieval.graphrag.retrieval import format_graph_context


class TestCanonicalTypes(unittest.TestCase):
    def test_aliases_map_to_taxonomy(self):
        self.assertEqual(canonical_entity_type('антибиотик'), 'Drug')
        self.assertEqual(canonical_entity_type('DISEASE'), 'Disease')
        self.assertEqual(canonical_entity_type('lekarstvennoe sredstvo'), 'Class')

    def test_relation_type_sanitized(self):
        # Latin words become UPPER_SNAKE; anything else collapses to RELATED_TO,
        # which keeps the interpolated Neo4j relationship type always safe.
        self.assertEqual(canonical_relation_type('Causes adverse effect'), 'CAUSES_ADVERSE_EFFECT')
        self.assertEqual(canonical_relation_type('a`b--c'), 'A_B_C')
        self.assertEqual(canonical_relation_type('вызывает побочку'), 'RELATED_TO')
        self.assertEqual(canonical_relation_type('вызывает'), 'CAUSES')
        self.assertEqual(canonical_relation_type('противопоказан'), 'CONTRAINDICATED_IN')
        self.assertNotIn('`', canonical_relation_type('x`)]-inject'))


class TestParseExtraction(unittest.TestCase):
    def test_plain_json(self):
        raw = (
            '{"entities":[{"name":"Амоксициллин","type":"Drug","description":"антибиотик"},'
            '{"name":"Анафилактический шок","type":"Disease","description":""}],'
            '"relations":[{"source":"Амоксициллин","target":"Анафилактический шок",'
            '"type":"causes","strength":0.9,"evidence":"вплоть до"}]}'
        )
        res = parse_extraction(raw)
        self.assertIsNone(res.error)
        self.assertEqual(len(res.entities), 2)
        self.assertEqual(res.entities[0].name, 'Амоксициллин')
        self.assertEqual(res.relations[0].type, 'CAUSES')
        self.assertAlmostEqual(res.relations[0].strength, 0.9)

    def test_markdown_fenced_and_prose(self):
        raw = 'Вот результат:\n```json\n{"entities":[{"name":"Жар","type":"Symptom","description":""}],"relations":[]}\n```\nГотово.'
        res = parse_extraction(raw)
        self.assertIsNone(res.error)
        self.assertEqual(res.entities[0].name, 'Жар')

    def test_relations_dropped_when_endpoints_missing(self):
        raw = '{"entities":[{"name":"Аспаркам","type":"Drug","description":""}],"relations":[{"source":"Аспаркам","target":"Варфарин","type":"X"}]}'
        res = parse_extraction(raw)
        self.assertEqual(len(res.entities), 1)
        # Варфарин is not an extracted entity; keeping the edge would invent a node.
        self.assertEqual(len(res.relations), 0)

    def test_endpoint_normalization_to_extracted_name(self):
        raw = (
            '{"entities":[{"name":"Амоксициллин","type":"Drug","description":""},'
            '{"name":"Шок","type":"Disease","description":""}],'
            '"relations":[{"source":"амоксициллин","target":"шок","type":"CAUSES"}]}'
        )
        res = parse_extraction(raw)
        self.assertEqual(len(res.relations), 1)
        # Names are rewritten to the extracted entities' canonical spelling.
        self.assertEqual(res.relations[0].source, 'Амоксициллин')
        self.assertEqual(res.relations[0].target, 'Шок')

    def test_garbage(self):
        for raw in ('', '   ', 'никакой не JSON', '[1,2,3]', '{"entities":"not-a-list"}'):
            res = parse_extraction(raw)
            self.assertIsNotNone(res.error, raw)

    def test_duplicates_and_empty_names(self):
        raw = (
            '{"entities":[{"name":"Жар","type":"Symptom","description":""},'
            '{"name":"жар","type":"Symptom","description":"та же"},'
            '{"name":"  ","type":"Symptom","description":""}],"relations":[]}'
        )
        res = parse_extraction(raw)
        self.assertEqual(len(res.entities), 1)


class TestRouter(unittest.TestCase):
    def setUp(self):
        # should_use_graph is gated on the master switch; the router logic is
        # what this class covers.
        from open_webui.retrieval.graphrag import orchestrator

        self._patch = unittest.mock.patch.object(orchestrator, 'graph_enabled', lambda: True)
        self._patch.start()
        self.addCleanup(self._patch.stop)

    def test_relation_queries_route_to_graph(self):
        for q in (
            'какие взаимодействия между амоксициллином и варфарином',
            'противопоказан ли препарат при беременности',
            'что входит в группу пенициллинов',
        ):
            self.assertTrue(should_use_graph(q), q)

    def test_factual_queries_stay_on_vector(self):
        for q in (
            'что говорит приказ 323',
            'какой размер чанка',
            'привет',
            'Перечисли разделы документа',
        ):
            self.assertFalse(should_use_graph(q), q)

    def test_signal_counts_distinct_cues(self):
        self.assertGreaterEqual(relation_signal('взаимодействие и побочные эффекты'), 2)


class TestFormatContext(unittest.TestCase):
    def test_triples_rendered(self):
        found = [
            {
                'id': 'e1',
                'gid': 'f1',
                'name': 'Амоксициллин',
                'type': 'Drug',
                'description': 'антибиотик',
                'score': 0.8,
            },
        ]
        neighbors = [
            {
                'from_id': 'e1',
                'from_gid': 'f1',
                'mid': 'e2',
                'mgid': 'f1',
                'mname': 'Шок',
                'mtype': 'Disease',
                'mdesc': '',
                'hops': 1,
                'types': ['CAUSES'],
                'strengths': [0.9],
            },
        ]
        text = format_graph_context(found, neighbors)
        self.assertIn('Амоксициллин', text)
        self.assertIn('CAUSES', text)
        self.assertIn('Сущность:', text)
        self.assertIn('Связь:', text)

    def test_dedup_neighbors(self):
        found = [
            {'id': 'e1', 'gid': 'f1', 'name': 'Амоксициллин', 'type': 'Drug', 'description': '', 'score': 0.8},
        ]
        dup = {
            'from_id': 'e1',
            'from_gid': 'f1',
            'mid': 'e2',
            'mgid': 'f1',
            'mname': 'Шок',
            'mtype': 'Disease',
            'mdesc': '',
            'hops': 1,
            'types': ['CAUSES'],
            'strengths': [0.9],
        }
        text = format_graph_context(found, [dup, dict(dup)])
        self.assertEqual(text.count('Связь:'), 1)

    def test_truncation_keeps_lines(self):
        found = [
            {'id': f'e{i}', 'gid': 'f1', 'name': f'Н{i}', 'type': 'Class', 'description': 'описание', 'score': 0.9}
            for i in range(200)
        ]
        text = format_graph_context(found, [], max_chars=300)
        self.assertLessEqual(len(text), 300)
        self.assertTrue(all(line.strip() for line in text.split('\n')))


if __name__ == '__main__':
    unittest.main(verbosity=2)
