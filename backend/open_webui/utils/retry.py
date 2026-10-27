"""Retry / backoff helpers for outbound LLM provider calls.

External model providers (OpenAI-compatible endpoints, Ollama backends,
Anthropic, image-generation services) can fail transiently due to network
hiccups, cold starts or rate limiting.  These helpers centralise a bounded
exponential-backoff policy with jitter so individual call sites stay small.

Usage:

    from open_webui.utils.retry import retry_with_backoff

    result = await retry_with_backoff(
        lambda: send_get_request(...),
        retry_on=(aiohttp.ClientError, asyncio.TimeoutError),
    )

The number of attempts and the backoff base delay are configurable via the
``LLM_RETRY_ATTEMPTS`` and ``LLM_RETRY_BASE_DELAY`` environment variables.
Only *transient* failures should be retried; HTTP 4xx responses raised as
``HTTPException`` are never retried by default.
"""

from __future__ import annotations

import asyncio
import logging
import random
from collections.abc import Awaitable, Callable

from open_webui.env import LLM_RETRY_ATTEMPTS, LLM_RETRY_BASE_DELAY

log = logging.getLogger(__name__)


def is_retryable_status(status: int | None) -> bool:
    """Return True when an upstream HTTP status warrants a retry."""
    if status is None:
        return False
    # 408 Request Timeout, 425 Too Early, 429 Too Many Requests,
    # and all 5xx server errors are considered transient.
    return status in (408, 425, 429) or 500 <= status < 600


async def retry_with_backoff(
    factory: Callable[[], Awaitable],
    *,
    attempts: int = LLM_RETRY_ATTEMPTS,
    base_delay: float = LLM_RETRY_BASE_DELAY,
    max_delay: float = 30.0,
    retry_on: tuple[type[BaseException], ...] = (Exception,),
    operation: str = 'request',
):
    """Execute an async callable with bounded exponential backoff + jitter.

    ``factory`` must be a zero-argument coroutine factory (a fresh awaitable
    is required for every attempt). Exceptions listed in ``retry_on`` are
    retried; anything else propagates immediately. The final exception is
    re-raised once all attempts are exhausted.
    """
    last_exc: BaseException | None = None
    for attempt in range(1, max(1, attempts) + 1):
        try:
            return await factory()
        except asyncio.CancelledError:
            raise
        except retry_on as exc:  # noqa: B902 - policy supplied by caller
            last_exc = exc
            if attempt >= attempts:
                break
            # Exponential backoff with full jitter (AWS architecture blog).
            delay = min(max_delay, base_delay * (2 ** (attempt - 1)))
            delay = random.uniform(0, delay)
            log.warning(
                f'Retry {operation}: attempt {attempt}/{attempts} failed ({exc!r}); '
                f'retrying in {delay:.2f}s'
            )
            await asyncio.sleep(delay)

    assert last_exc is not None
    raise last_exc
