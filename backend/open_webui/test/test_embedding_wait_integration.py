"""Integration test for the embedding wait-loop against a real asyncio event loop.

Where test_embedding_wait.py stubs the future to check control flow, this drives
`await_embedding` from a worker thread against coroutines on a live loop, mirroring how
save_docs_to_vector_db() waits on run_coroutine_threadsafe(). It catches what a stub
cannot: a wedged coroutine left running after the waiter gives up, and a waiter that
starves the loop it is waiting on -- which is exactly how the first version of this test
failed, since blocking the loop's own thread means no coroutine ever advances.

Run: python3 backend/open_webui/test/test_embedding_wait_integration.py
"""

import asyncio
import importlib.util
import threading
import time
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location(
    'embedding_wait', str(Path(__file__).resolve().parents[1] / 'utils' / 'embedding_wait.py')
)
embedding_wait = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(embedding_wait)

failures = []


def check(name, ok, detail=''):
    print(f'{name} -> {"OK" if ok else "FAIL"} {detail}'.rstrip())
    if not ok:
        failures.append(name)


class BackgroundLoop:
    """Runs the event loop on its own thread, the way the app's main loop does."""

    def __enter__(self):
        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(target=self.loop.run_forever, daemon=True)
        self.thread.start()
        return self

    def __exit__(self, *_exc):
        self.loop.call_soon_threadsafe(self.loop.stop)
        self.thread.join(timeout=5)

    async def submit(self, coro, *, total_timeout=None, idle_timeout=None, poll=0.2, ticking=False):
        """Wait on `coro` from a worker thread and report the outcome without blocking the loop."""
        future = asyncio.run_coroutine_threadsafe(coro, self.loop)
        tick = {'at': time.monotonic()}
        box = {}

        def target():
            try:
                box['out'] = embedding_wait.await_embedding(
                    future,
                    total_timeout=total_timeout,
                    idle_timeout=idle_timeout,
                    last_progress_at=lambda: tick['at'],
                    poll_interval=poll,
                )
            except BaseException as exc:  # noqa: BLE001
                box['err'] = exc

        thread = threading.Thread(target=target)
        start = time.monotonic()
        thread.start()
        while thread.is_alive():
            if ticking:
                # Emulates the progress callback landing on the main loop.
                tick['at'] = time.monotonic()
            await asyncio.sleep(0.02)
        thread.join(timeout=30)
        return future, box, time.monotonic() - start


async def progressing_job(seconds=1.0):
    await asyncio.sleep(seconds)
    return ['e1', 'e2', 'e3']


async def wedged_job():
    await asyncio.sleep(10_000)  # never returns: the embedding server stopped answering


async def self_timed_out_job():
    await asyncio.sleep(0.2)
    raise TimeoutError('read timeout from embedding server')


async def main():
    with BackgroundLoop() as bg:
        # 1. Slower than the idle budget in total, but still finishing: must not be cut off.
        _, box, elapsed = await bg.submit(progressing_job(3.0), idle_timeout=1, ticking=True)
        check(
            'slow-but-progressing job completes',
            box.get('out') == ['e1', 'e2', 'e3'] and elapsed < 10,
            f'({elapsed:.1f}s)',
        )

        # 2. A wedged coroutine must be abandoned with the stall wording, not hang forever.
        future, box, waited = await bg.submit(wedged_job(), idle_timeout=1, ticking=False)
        err = box.get('err')
        check(
            'wedged job raises stalled',
            isinstance(err, embedding_wait.EmbeddingStalledError) and waited < 10,
            f'({waited:.1f}s)',
        )
        time.sleep(0.3)
        check('wedged coroutine actually cancelled', future.cancelled() or future.done())

        # 3. An operator-set ceiling keeps plain total-duration semantics.
        _, box, _ = await bg.submit(wedged_job(), total_timeout=1, idle_timeout=600, ticking=True)
        err = box.get('err')
        check(
            'explicit ceiling raises duration wording',
            isinstance(err, embedding_wait.EmbeddingTimeoutError) and 'within 1s' in str(err),
        )

        # 4. The job's own timeout surfaces untouched -- on 3.11 the timeout classes are
        #    identical, so this can only be told apart by the future being already done.
        future, box, waited = await bg.submit(self_timed_out_job(), idle_timeout=30, ticking=True)
        err = box.get('err')
        check(
            'coroutine timeout message preserved',
            isinstance(err, TimeoutError)
            and not isinstance(err, embedding_wait.EmbeddingStalledError)
            and str(err) == 'read timeout from embedding server',
            f'({type(err).__name__}, {waited:.1f}s)',
        )
        check(
            'failed job exits promptly, no busy-loop',
            waited < 2.0 and future.done(),
            f'({waited:.1f}s against a 30s idle budget)',
        )

    print('---')
    if failures:
        print(f'FAILED: {", ".join(failures)}')
        raise SystemExit(1)
    print('ALL OK')


if __name__ == '__main__':
    asyncio.run(main())
