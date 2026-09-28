"""Integration test for the Neo4j gateway against a live server.

Skips unless a reachable Neo4j is configured (env NEO4J_TEST_URI / the app's
NEO4J_URI), so it stays green in environments without the sidecar. Uses a throw-
away gid and removes it at the end — never touches real document graphs.

Run (from repo root):
  NEO4J_TEST_URI=bolt://localhost:7687 NEO4J_TEST_USER=neo4j \
  NEO4J_TEST_PASSWORD=... \
  python3 backend/open_webui/test/test_graphrag_neo4j.py
"""

import os
import sys
import unittest
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[2]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

DIM = 1024  # the production vector index dimension — see setUpClass comment
URI = os.getenv('NEO4J_TEST_URI') or os.getenv('NEO4J_URI')
USER = os.getenv('NEO4J_TEST_USER') or os.getenv('NEO4J_USER', 'neo4j')
PASSWORD = os.getenv('NEO4J_TEST_PASSWORD') or os.getenv('NEO4J_PASSWORD', '')

from open_webui.retrieval.graphrag.neo4j_client import Neo4jGraph


def vec(seed):
    # Deterministic unit-ish vector, DIM long, distinct per seed.
    base = [((seed * 37 + i * 11) % 97) / 97.0 + 0.01 for i in range(DIM)]
    norm = sum(x * x for x in base) ** 0.5
    return [x / norm for x in base]


@unittest.skipIf(not URI, 'no Neo4j under test (set NEO4J_TEST_URI)')
class TestNeo4jGraph(unittest.TestCase):
    gid = 'graphrag-test-' + os.urandom(4).hex()

    @classmethod
    def setUpClass(cls):
        # Shares the production index: Neo4j dedupes vector indexes by
        # (label, property), so a second name over the same pair is a silent
        # no-op under IF NOT EXISTS. Isolation comes from the unique gid,
        # deleted in teardown.
        cls.graph = Neo4jGraph(URI, USER, PASSWORD, embedding_dim=DIM)
        cls.graph.verify()
        cls.graph.ensure_schema()
        cls.graph.delete_gid(cls.gid)  # clean slate

    @classmethod
    def tearDownClass(cls):
        cls.graph.delete_gid(cls.gid)
        cls.graph.close()

    def test_01_chunk_lifecycle(self):
        self.graph.upsert_chunk(self.gid, 'c1', 'hash1', 'текст чанка', 10, done=False)
        self.assertNotIn('hash1', self.graph.indexed_chunk_hashes(self.gid))
        self.graph.upsert_chunk(self.gid, 'c1', 'hash1', 'текст чанка', 10, done=True)
        self.assertIn('hash1', self.graph.indexed_chunk_hashes(self.gid))

    def test_02_entities_and_relations(self):
        ents = [
            {
                'id': 'e_amox',
                'name': 'Амоксициллин',
                'type': 'Drug',
                'description': 'антибиотик',
                'embedding': vec(1),
                'chunk_ids': ['c1'],
            },
            {
                'id': 'e_shock',
                'name': 'Анафилактический шок',
                'type': 'Disease',
                'description': '',
                'embedding': vec(2),
                'chunk_ids': ['c1'],
            },
        ]
        n = self.graph.upsert_entities(self.gid, ents)
        self.assertEqual(n, 2)
        rels = [
            {
                'source': 'e_amox',
                'target': 'e_shock',
                'type': 'CAUSES',
                'strength': 0.9,
                'evidence': 'вплоть до шока',
                'chunk_id': 'c1',
            }
        ]
        self.assertEqual(self.graph.upsert_relations(self.gid, rels), 1)
        # stats.relations counts Entity->Entity only — the structural
        # Chunk-[:MENTIONS]->Entity edges must not inflate it.
        self.assertEqual(self.graph.stats([self.gid])['relations'], 1)

    def test_03_entity_idempotent_merge(self):
        # Re-extracting the same entity must not duplicate the node.
        before = self.graph.stats([self.gid])['entities']
        self.graph.upsert_entities(
            self.gid,
            [
                {
                    'id': 'e_amox',
                    'name': 'Амоксициллин',
                    'type': 'Drug',
                    'description': 'более длинное описание препарата',
                    'embedding': vec(1),
                    'chunk_ids': ['c1'],
                },
            ],
        )
        self.assertEqual(self.graph.stats([self.gid])['entities'], before)
        # Longer description wins on merge.
        hit = self.graph.vector_search(vec(1), 3, [self.gid])[0]
        self.assertEqual(hit['name'], 'Амоксициллин')
        self.assertIn('более длинное', hit['description'])

    def test_04_vector_search_filters_by_gid(self):
        found = self.graph.vector_search(vec(1), 5, [self.gid])
        self.assertTrue(found)
        self.assertTrue(all(f['gid'] == self.gid for f in found))
        # A foreign gid must see none of ours.
        other = self.graph.vector_search(vec(1), 5, ['no-such-gid'])
        self.assertEqual(other, [])

    def test_05_neighbors(self):
        nb = self.graph.neighbors([('e_amox', self.gid)], depth=1, limit_per=5)
        self.assertTrue(any(n['mid'] == 'e_shock' and 'CAUSES' in n['types'] for n in nb))

    def test_05b_neighbors_skip_structural_edges(self):
        # e_amox and e_shock share chunk c1, so at depth 2 they are also
        # "adjacent" through Chunk-[:MENTIONS]->Entity. Those edges carry no
        # strength and used to surface at the coalesce() default of 1.0,
        # outranking the real relation in the text handed to the model.
        nb = self.graph.neighbors([('e_amox', self.gid)], depth=2, limit_per=20)
        self.assertTrue(nb, 'depth-2 traversal returned nothing')
        for row in nb:
            self.assertNotIn('MENTIONS', row['types'], f'structural edge leaked: {row}')
        # ...without over-filtering: the genuine edge is still reported.
        self.assertTrue(any(n['mid'] == 'e_shock' and 'CAUSES' in n['types'] for n in nb))

    def test_06_top_entities(self):
        top = self.graph.top_entities(self.gid, limit=10)
        names = {t['name'] for t in top}
        self.assertIn('Амоксициллин', names)

    def test_07_delete_gid_isolated(self):
        self.assertGreater(self.graph.stats([self.gid])['entities'], 0)
        removed = self.graph.delete_gid(self.gid)
        self.assertGreater(removed, 0)
        self.assertEqual(self.graph.stats([self.gid])['entities'], 0)
        # Other graphs untouched (can't assert much on a fresh server, but no error).
        self.graph.stats()


if __name__ == '__main__':
    unittest.main(verbosity=2)
