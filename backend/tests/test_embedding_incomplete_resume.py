"""Wiring test: an interrupted embedding must keep the file searchable and resume.

When the embedding job hits the operator-set ceiling after some batches already
landed in the vector store (`save_docs_to_vector_db` raises
`EmbeddingIncompleteError`), `process_file` must NOT fall through to the generic
failure path — that marks the file `failed`, clears its hash and returns HTTP 400,
which is exactly the reported bug: a large document never shows up in the
knowledge base listing, and its remaining chunks are never embedded.

The intended behaviour is: mark the file `completed` (so it appears in the KB
list and its persisted chunks are searchable), then fire a detached
`resume_incomplete_embedding` task that re-runs `save_docs_to_vector_db` until the
collection stops growing.

Checked on the AST of the router rather than by importing it: pulling in
`routers.retrieval` registers ORM tables with dangling foreign keys in
`Base.metadata`, which breaks unrelated tests that call `create_all()`.

Run: python3 backend/tests/test_embedding_incomplete_resume.py
"""

import ast
import unittest
from pathlib import Path

RETRIEVAL_PY = Path(__file__).resolve().parent.parent / 'open_webui' / 'routers' / 'retrieval.py'


def node_by_name(tree: ast.AST, name: str) -> ast.AST:
    for node in ast.walk(tree):
        if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)) and node.name == name:
            return node
    raise AssertionError(f'{name} not found in retrieval.py')


def handlers_within(fn: ast.AST, try_node: ast.Try):
    return [h for h in try_node.handlers]


def enclosing_try(fn: ast.AST, lineno: int):
    """The tightest `try` whose body/orelse contains `lineno`."""
    candidates = [
        node
        for node in ast.walk(fn)
        if isinstance(node, ast.Try) and node.lineno <= lineno <= (node.end_lineno or node.lineno)
    ]
    if not candidates:
        return None
    return min(candidates, key=lambda node: (node.end_lineno or node.lineno) - node.lineno)


def source_of(node: ast.AST) -> str:
    return ast.unparse(node)


class TestEmbeddingIncompleteWiring(unittest.TestCase):
    def setUp(self):
        self.tree = ast.parse(RETRIEVAL_PY.read_text(encoding='utf-8'))
        self.save = node_by_name(self.tree, 'save_docs_to_vector_db')
        self.process = node_by_name(self.tree, 'process_file')
        self.resume = node_by_name(self.tree, 'resume_incomplete_embedding')

    # ── save_docs_to_vector_db: the progressive core ──────────────────────

    def test_on_batch_declares_nonlocal_expected_dim(self):
        """`expected_dim` is assigned inside `_on_batch`, so without `nonlocal`
        the first batch raises UnboundLocalError and progressive indexing never
        runs.  The closure must forward writes to the enclosing scope."""
        on_batch = next(
            n
            for n in ast.walk(self.save)
            if isinstance(n, ast.AsyncFunctionDef) and n.name == '_on_batch'
        )
        nonlocals = [n for n in ast.walk(on_batch) if isinstance(n, ast.Nonlocal)]
        self.assertTrue(nonlocals, '_on_batch must declare nonlocal expected_dim')
        self.assertIn('expected_dim', nonlocals[0].names)

    def test_on_batch_persists_each_batch_immediately(self):
        """Each finished batch goes straight to the vector store from the
        callback, not accumulated for a final bulk insert."""
        on_batch = next(
            n
            for n in ast.walk(self.save)
            if isinstance(n, ast.AsyncFunctionDef) and n.name == '_on_batch'
        )
        sources = [source_of(n) for n in ast.walk(on_batch) if isinstance(n, ast.Call)]
        self.assertTrue(
            any('VECTOR_DB_CLIENT.insert' in s for s in sources),
            'expected VECTOR_DB_CLIENT.insert inside _on_batch',
        )

    def test_deterministic_chunk_ids_used(self):
        """Resumability rests on stable ids derived from collection/file/offset."""
        sources = [source_of(n) for n in ast.walk(self.save) if isinstance(n, ast.Call)]
        self.assertTrue(
            any('_deterministic_chunk_id(' in s for s in sources),
            'expected _deterministic_chunk_id call in save_docs_to_vector_db',
        )

    def test_incomplete_error_raised_after_partial_persist(self):
        """Cut-short embedding surfaces as EmbeddingIncompleteError, not a bare
        TimeoutError, so the caller can distinguish 'some chunks saved' from
        'nothing saved'."""
        raised = [
            source_of(n)
            for n in ast.walk(self.save)
            if isinstance(n, ast.Raise) and 'EmbeddingIncompleteError' in source_of(n)
        ]
        self.assertEqual(len(raised), 1)
        self.assertIn('persisted_any[', raised[0])

    # ── process_file: the reported bug (file dropped from KB on timeout) ──

    def test_process_file_handles_incomplete_error(self):
        """process_file must have an except clause for EmbeddingIncompleteError
        placed before the generic Exception handler."""
        handlers = [
            h
            for n in ast.walk(self.process)
            if isinstance(n, ast.Try)
            for h in n.handlers
            if h.type is not None and 'EmbeddingIncompleteError' in source_of(h.type)
        ]
        self.assertEqual(len(handlers), 1, 'expected exactly one EmbeddingIncompleteError handler')

        handler = handlers[0]
        body = [source_of(n) for n in handler.body]
        # The handler schedules the resume task.
        self.assertTrue(
            any('resume_incomplete_embedding(' in s for s in body),
            'handler must schedule resume_incomplete_embedding',
        )
        # ...and keeps the file in the KB listing as completed.
        self.assertTrue(
            any("'status': 'completed'" in s or "'status' : 'completed'" in s for s in body),
            'handler must mark the file completed',
        )

    def test_incomplete_handler_precedes_generic_exception(self):
        """The dedicated handler is useless if the generic `except Exception`
        in the same try runs first and flags the file failed."""
        try_nodes = [n for n in ast.walk(self.process) if isinstance(n, ast.Try)]
        matched = False
        for t in try_nodes:
            handler_names = [('*' if h.type is None else source_of(h.type)) for h in t.handlers]
            if any('EmbeddingIncompleteError' in name for name in handler_names):
                matched = True
                self.assertEqual(handler_names[0], 'EmbeddingIncompleteError')
                self.assertTrue(
                    any(name == '*' or name == 'Exception' for name in handler_names[1:]),
                    'generic exception handler must follow the incomplete handler',
                )
        self.assertTrue(matched, 'no try block in process_file has an EmbeddingIncompleteError handler')

    # ── resume_incomplete_embedding: background continuation ──────────────

    def test_resume_runs_save_in_a_threadpool(self):
        """The resume coroutine runs on the main loop; save_docs_to_vector_db is
        synchronous and blocks its calling thread via run_coroutine_threadsafe, so
        it must be dispatched to a worker thread or the loop deadlocks."""
        calls = [source_of(n) for n in ast.walk(self.resume) if isinstance(n, ast.Call)]
        self.assertTrue(
            any('run_in_threadpool(' in s and 'save_docs_to_vector_db' in s for s in calls),
            'expected run_in_threadpool(save_docs_to_vector_db, ...) in resume',
        )

    def test_resume_is_async_and_dedups(self):
        self.assertIsInstance(self.resume, ast.AsyncFunctionDef)
        # Guard set prevents concurrent re-embedding of the same (collection, file).
        sources = [source_of(n) for n in ast.walk(self.resume)]
        self.assertTrue(
            any('_embedding_resume_running' in s for s in sources),
            'expected resume to guard against duplicate concurrent runs',
        )


if __name__ == '__main__':
    unittest.main(verbosity=2)
