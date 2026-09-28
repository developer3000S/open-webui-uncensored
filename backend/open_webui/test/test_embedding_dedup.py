"""Tests for embedding reuse of byte-identical documents.

Indexing costs ~12.5s per 460-token chunk on this machine's CPU-only Ollama, and the
corpus duplicates heavily, so a file whose extracted text hashes to an already-indexed
file's hash gets those vectors copied instead of recomputed. Copying is only correct
when the stored vectors came from the same embedding engine and model and the text
splits the same way — a vector adopted for text it was not computed from corrupts
retrieval silently, because the vector store cannot tell borrowed vectors apart.

Run: python3 backend/open_webui/test/test_embedding_dedup.py
"""

import sys
import unittest
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[2]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

try:
    from open_webui.retrieval.dedup import reused_embedding_items
    from open_webui.retrieval.vector.main import VectorItem
except ModuleNotFoundError as exc:  # pragma: no cover - host without deps
    raise SystemExit(
        f'skip: this test needs the application dependencies ({exc.name}). '
        'Run it inside the container or in an installed venv.'
    )


ENGINE = 'ollama'
MODEL = 'qllama/multilingual-e5-large:Q4_K_M'
HASH = 'a' * 64


def source(text, vector=None, engine=ENGINE, model=MODEL, hash=HASH):
    """One stored chunk, as it comes back from get_with_embeddings."""
    return VectorItem(
        id='src-1',
        text=text,
        vector=vector if vector is not None else [0.1, 0.2],
        metadata={
            'file_id': 'file-src',
            'hash': hash,
            'embedding_config': {'engine': engine, 'model': model},
        },
    )


def adopt(source_items, texts, stored_hash=HASH):
    """The reuse decision for indexing a file whose chunks are `texts`."""
    return reused_embedding_items(
        source_items,
        ENGINE,
        MODEL,
        {'file_id': 'file-new', 'name': 'МКБ-10 (test).docx', 'hash': stored_hash},
        texts,
        [{'file_id': 'file-new'} for _ in texts],
    )


class TestReusedEmbeddingItems(unittest.TestCase):
    def test_identical_chunks_are_adopted_with_new_metadata(self):
        """A copy of a document gets the source's vectors under the new file's id."""
        items = adopt(
            [source('Амебиаз A06'), source('Амебный абсцесс печени')],
            ['Амебиаз A06', 'Амебный абсцесс печени'],
        )
        self.assertIsNotNone(items)
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0]['vector'], [0.1, 0.2])
        self.assertEqual(items[0]['metadata']['file_id'], 'file-new')
        self.assertNotEqual(items[0]['id'], 'src-1')

    def test_order_follows_the_target_not_the_source(self):
        """Chunks arrive from the store in unspecified order; the mapping is by text."""
        items = adopt([source('B', vector=[2.0]), source('A', vector=[1.0])], ['A', 'B'])
        self.assertEqual(items[0]['vector'], [1.0])
        self.assertEqual(items[1]['vector'], [2.0])

    def test_different_embedding_model_is_refused(self):
        """Vectors from another model live in an unrelated space."""
        self.assertIsNone(adopt([source('А', model='qwen3-embedding:0.6b')], ['А']))

    def test_different_embedding_engine_is_refused(self):
        self.assertIsNone(adopt([source('А', engine='openai')], ['А']))

    def test_chunk_missing_from_source_is_refused(self):
        """A different splitter or chunk size yields different chunks: embed normally."""
        self.assertIsNone(adopt([source('Амебиаз A06')], ['Амебиаз', 'A06']))

    def test_different_hash_is_refused(self):
        """Hash equality is the contract for byte-identical text; a mismatch is a bug."""
        self.assertIsNone(adopt([source('А', hash='b' * 64)], ['А']))

    def test_embedding_config_stored_as_string_is_parsed(self):
        """Chroma stringifies dict metadata, so the real payload is a repr string."""
        item = source('А')
        item.metadata['embedding_config'] = str(item.metadata['embedding_config'])
        self.assertIsNotNone(adopt([item], ['А']))

    def test_unparseable_embedding_config_is_refused(self):
        item = source('А')
        item.metadata['embedding_config'] = 'ollama,not-a-dict'
        self.assertIsNone(adopt([item], ['А']))

    def test_no_source_means_embed_normally(self):
        for empty in (None, []):
            self.assertIsNone(adopt(empty, ['А']))

    def test_repeated_chunk_within_one_document(self):
        """The same text twice must take the same vector rather than fail."""
        items = adopt([source('А', vector=[3.0])], ['А', 'А'])
        self.assertEqual([i['vector'] for i in items], [[3.0], [3.0]])


if __name__ == '__main__':
    unittest.main(verbosity=2)
