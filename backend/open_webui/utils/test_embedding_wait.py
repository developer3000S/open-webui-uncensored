"""Tests for the embedding wait-loop in open_webui/utils/embedding_wait.py.

The module is loaded by file path rather than imported as `open_webui.utils.*` so these
tests run on a bare host without the application's dependencies installed
(`open_webui/__init__.py` imports typer, fastapi, ...).

Run with either:
    python3 -m unittest discover -s backend/open_webui/utils -p 'test_*.py'
    cd backend && pytest open_webui/utils/test_embedding_wait.py
"""

import importlib.util
import unittest
from concurrent.futures import TimeoutError as FuturesTimeout
from pathlib import Path
from typing import Callable, Optional

_SPEC = importlib.util.spec_from_file_location(
    'embedding_wait', str(Path(__file__).resolve().parent / 'embedding_wait.py')
)
embedding_wait = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(embedding_wait)

EMBEDDINGS = [[0.1, 0.2]]


class FakeClock:
    """Monotonic clock advanced by polling instead of by real time."""

    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class FakeFuture:
    """Stands in for the Future returned by asyncio.run_coroutine_threadsafe.

    `result(timeout)` blocks by advancing the shared clock, which lets the idle watchdog be
    exercised without sleeping in real time.
    """

    def __init__(
        self,
        clock: FakeClock,
        *,
        completes_after: Optional[float] = None,
        error: Optional[BaseException] = None,
        on_timeout: Optional[Callable[[], None]] = None,
    ) -> None:
        self.clock = clock
        self.completes_after = completes_after
        self.error = error
        self.on_timeout = on_timeout
        self.cancelled_count = 0
        self._done = error is not None

    def result(self, timeout: Optional[float] = None) -> list:
        if self._done and self.error:
            raise self.error
        if timeout is None:
            return EMBEDDINGS
        self.clock.advance(timeout)
        if self.on_timeout:
            self.on_timeout()
        if self.completes_after is not None and self.clock() >= self.completes_after:
            self._done = True
            return EMBEDDINGS
        raise FuturesTimeout

    def done(self) -> bool:
        return self._done

    def cancel(self) -> bool:
        self.cancelled_count += 1
        self._done = True
        return True

    @property
    def cancelled(self) -> bool:
        return self.cancelled_count > 0


class AwaitEmbeddingTest(unittest.TestCase):
    def setUp(self) -> None:
        self.clock = FakeClock()

    def _wait(self, future, **kwargs):
        kwargs.setdefault('poll_interval', 1)
        kwargs.setdefault('clock', self.clock)
        return embedding_wait.await_embedding(future, **kwargs)

    def test_returns_embeddings_when_job_completes(self) -> None:
        future = FakeFuture(self.clock, completes_after=1)
        result = self._wait(future, idle_timeout=10, last_progress_at=lambda: self.clock())
        self.assertEqual(result, EMBEDDINGS)
        self.assertFalse(future.cancelled)

    def test_slow_but_progressing_job_is_not_killed(self) -> None:
        """The regression this guard exists for. A large document on a CPU-only embedding
        server legitimately runs for hours; as long as it keeps ticking it must not be
        abandoned, even though total elapsed time exceeds idle_timeout."""
        last_tick = {'at': 0.0}
        # 9 polls of 1s each, well past an idle budget of 5s, but with a fresh tick per poll.
        future = FakeFuture(
            self.clock,
            completes_after=9,
            on_timeout=lambda: last_tick.__setitem__('at', self.clock()),
        )
        result = self._wait(future, idle_timeout=5, last_progress_at=lambda: last_tick['at'])
        self.assertEqual(result, EMBEDDINGS)
        self.assertFalse(future.cancelled)

    def test_wedged_job_raises_stalled(self) -> None:
        future = FakeFuture(self.clock, completes_after=10_000)
        tick = {'at': 0.0}  # never moves again: the embedding server stopped answering
        with self.assertRaises(embedding_wait.EmbeddingStalledError) as ctx:
            self._wait(future, idle_timeout=5, last_progress_at=lambda: tick['at'])
        self.assertEqual(ctx.exception.stalled_for, 6)
        self.assertIn('no progress', str(ctx.exception))
        self.assertTrue(future.cancelled, 'a leaked coroutine keeps hammering the server')

    def test_total_timeout_wins_and_reports_duration(self) -> None:
        """An operator-set RAG_EMBEDDING_TIMEOUT keeps its plain total-duration meaning."""
        future = FakeFuture(self.clock, completes_after=10_000)
        with self.assertRaises(embedding_wait.EmbeddingTimeoutError) as ctx:
            self._wait(future, total_timeout=4, idle_timeout=1000, last_progress_at=lambda: 0.0)
        self.assertIn('within 4s', str(ctx.exception))
        self.assertTrue(future.cancelled)

    def test_job_error_is_re_raised_untouched(self) -> None:
        """asyncio.TimeoutError, concurrent.futures.TimeoutError and the builtin TimeoutError
        are one class on 3.11, so a job that timed out on its own HTTP call arrives here
        indistinguishably by type. Its own message must survive, not get rewritten into one
        of our two wordings."""
        future = FakeFuture(self.clock, error=TimeoutError('read timeout from embedding server'))
        with self.assertRaises(TimeoutError) as ctx:
            self._wait(future, idle_timeout=5, last_progress_at=lambda: self.clock())
        self.assertEqual(str(ctx.exception), 'read timeout from embedding server')
        self.assertNotIsInstance(ctx.exception, embedding_wait.EmbeddingStalledError)
        self.assertNotIsInstance(ctx.exception, embedding_wait.EmbeddingTimeoutError)
        self.assertTrue(future.cancelled)

    def test_non_timeout_error_also_cancels(self) -> None:
        future = FakeFuture(self.clock, error=ConnectionResetError('Server disconnected'))
        with self.assertRaises(ConnectionResetError):
            self._wait(future, idle_timeout=5, last_progress_at=lambda: self.clock())
        self.assertTrue(future.cancelled)

    def test_without_progress_callback_waits_plainly(self) -> None:
        """Callers that report no progress keep the original semantics: single blocking
        result() call, no polling loop and no idle bound."""
        future = FakeFuture(self.clock)
        result = embedding_wait.await_embedding(future)
        self.assertEqual(result, EMBEDDINGS)
        self.assertFalse(future.cancelled)


if __name__ == '__main__':
    unittest.main()
