"""Deadline handling for the embedding job that runs on the main event loop.

Kept free of FastAPI/config imports so the control flow is unit-testable without
booting the application.
"""

import logging
from collections.abc import Callable
from concurrent.futures import Future
from concurrent.futures import TimeoutError as FuturesTimeout
from time import monotonic

log = logging.getLogger(__name__)


class EmbeddingStalledError(Exception):
    """The embedding job stopped reporting progress."""

    def __init__(self, stalled_for: int, idle_timeout: int) -> None:
        super().__init__(
            f'Embedding made no progress for {stalled_for}s (limit {idle_timeout}s). '
            'The embedding server may be overloaded or unreachable; retry the upload, raise '
            'RAG_EMBEDDING_IDLE_TIMEOUT, or use a faster embedding engine.'
        )
        self.stalled_for = stalled_for
        self.idle_timeout = idle_timeout


class EmbeddingTimeoutError(Exception):
    """The embedding job exceeded an operator-set total duration."""

    def __init__(self, timeout: float) -> None:
        super().__init__(
            f'Embedding did not finish within {int(timeout)}s. The embedding server may be '
            'overloaded or unreachable; retry the upload or raise RAG_EMBEDDING_TIMEOUT.'
        )
        self.timeout = timeout


def await_embedding(
    future: Future,
    *,
    total_timeout: float | None = None,
    idle_timeout: float | None = None,
    last_progress_at: Callable[[], float] | None = None,
    poll_interval: float = 30,
    clock: Callable[[], float] = monotonic,
) -> list:
    """Block on `future` without letting a wedged embedding server hang the upload forever.

    `total_timeout` is an operator-set ceiling and keeps its plain total-duration meaning.
    Without it, the bound is progress-based: a large document on a CPU-only embedding
    server legitimately runs for hours, so only a run that stops emitting ticks counts as
    wedged. `last_progress_at` returns the monotonic timestamp of the most recent tick and
    must be cheap and non-blocking.

    Cancels the future on every failure path; leaving it running would keep hammering the
    embedding server after the file has already been reported as failed.
    """
    try:
        if total_timeout is not None:
            return future.result(timeout=total_timeout)
        if idle_timeout is None or last_progress_at is None:
            return future.result()
        while True:
            try:
                return future.result(timeout=poll_interval)
            except FuturesTimeout:
                # A completed future re-raises its stored exception instantly, so this
                # branch also sees the job's own failures as FuturesTimeout (the timeout
                # classes are identical on 3.11). Passing those straight through is what
                # keeps the loop from spinning at full CPU on a permanently-failed job.
                if future.done():
                    raise
                stalled = clock() - last_progress_at()
                if stalled > idle_timeout:
                    raise EmbeddingStalledError(int(stalled), int(idle_timeout)) from None
    except (EmbeddingStalledError, EmbeddingTimeoutError):
        future.cancel()
        raise
    except FuturesTimeout:
        # On Python 3.11 asyncio.TimeoutError, concurrent.futures.TimeoutError and the
        # builtin TimeoutError are one and the same class, so a job that failed with its own
        # timeout lands here too. Completion state tells them apart: a finished future
        # carried a real error, which is re-raised untouched rather than rewritten below.
        job_failed = future.done()
        future.cancel()
        if job_failed:
            raise
        if total_timeout is not None:
            raise EmbeddingTimeoutError(total_timeout) from None
        raise
    except BaseException:
        # Any other embedding failure (HTTP error, connection reset) must not leave the
        # coroutine running against the embedding server in the background.
        future.cancel()
        raise
