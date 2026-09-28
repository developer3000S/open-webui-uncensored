"""Wiring test: the knowledge-base pass must not re-split already-chunked docs.

The upload pipeline indexes a file into `file-{id}` (first pass, splitting raw text),
then reads those chunks back to index them into the knowledge base (second pass). The
read-back documents are already at their final boundaries, so splitting them again
rewrites every chunk text and embedding reuse declines on all of them — measured on
2026-09-11: 9 declines, 0 successes, and each second pass re-embedded a whole document
whose vectors were seconds old.

Checked on the AST of the router rather than by importing it: pulling in
`routers.retrieval` registers ORM tables with dangling foreign keys in `Base.metadata`,
which breaks unrelated tests that call `create_all()`.

Run: python3 backend/open_webui/test/test_embedding_reuse_wiring.py
"""

import ast
import unittest
from pathlib import Path

RETRIEVAL_PY = Path(__file__).resolve().parents[1] / 'routers/retrieval.py'


def process_file_node() -> ast.AsyncFunctionDef:
    tree = ast.parse(RETRIEVAL_PY.read_text(encoding='utf-8'))
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef) and node.name == 'process_file':
            return node
    raise AssertionError('process_file not found in retrieval.py')


def save_calls(fn: ast.AST):
    """Calls that reach save_docs_to_vector_db, directly or via run_in_threadpool."""
    calls = []
    for node in ast.walk(fn):
        if not isinstance(node, ast.Call):
            continue
        name = getattr(node.func, 'id', '')
        if name == 'save_docs_to_vector_db':
            calls.append(node)
        elif name == 'run_in_threadpool' and node.args and getattr(node.args[0], 'id', '') == 'save_docs_to_vector_db':
            calls.append(node)
    return calls


def enclosing_if(fn: ast.AST, lineno: int):
    """The tightest `if` whose body contains `lineno`."""
    candidates = [
        node
        for node in ast.walk(fn)
        if isinstance(node, ast.If) and node.lineno <= lineno <= (node.end_lineno or node.lineno)
    ]
    if not candidates:
        return None
    return min(candidates, key=lambda node: (node.end_lineno or node.lineno) - node.lineno)


class TestKbPassSplitWiring(unittest.TestCase):
    def setUp(self):
        self.fn = process_file_node()

    def test_kb_pass_forwards_split_with_the_pre_split_flag(self):
        """Exactly one save call in process_file, and its split is `(not chunks_pre_split)`.

        Anything else — a literal True, or no split kwarg at all (default True) —
        silently reinstates the double-split and makes reuse decline on every file.
        """
        calls = save_calls(self.fn)
        self.assertEqual(len(calls), 1)
        kwargs = {kw.arg: ast.unparse(kw.value) for kw in calls[0].keywords if kw.arg}
        self.assertEqual(kwargs.get('split'), 'not chunks_pre_split')

    def test_flag_is_initialized_false(self):
        """The raw-text branches must keep splitting, so the default stays False."""
        inits = [
            node
            for node in ast.walk(self.fn)
            if isinstance(node, ast.Assign)
            and any(isinstance(t, ast.Name) and t.id == 'chunks_pre_split' for t in node.targets)
            and ast.unparse(node.value) == 'False'
        ]
        self.assertEqual(len(inits), 1)
        first_docs = min(
            node.lineno
            for node in ast.walk(self.fn)
            if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'docs' for t in node.targets)
        )
        self.assertLess(inits[0].lineno, first_docs)

    def test_only_the_chunk_readback_branch_raises_the_flag(self):
        """`chunks_pre_split = True` belongs to the branch that queries `file-{id}`.

        Marking the loader branch or the content branch would index under-sized chunks
        into the knowledge base and change what raw uploads produce.
        """
        assignments = [
            node
            for node in ast.walk(self.fn)
            if isinstance(node, ast.Assign)
            and any(isinstance(t, ast.Name) and t.id == 'chunks_pre_split' for t in node.targets)
            and ast.unparse(node.value) == 'True'
        ]
        self.assertEqual(len(assignments), 1)
        guard = enclosing_if(self.fn, assignments[0].lineno)
        self.assertIsNotNone(guard)
        test_src = ast.unparse(guard.test)
        self.assertIn('ids', test_src)
        self.assertIn('result', test_src)


if __name__ == '__main__':
    unittest.main(verbosity=2)
