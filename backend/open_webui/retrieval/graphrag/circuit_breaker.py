"""Circuit breaker for external retrieval dependencies (rec 3.2).

The orchestrator already degrades gracefully when Neo4j or the embedding
provider fails (fail-closed to the native pipeline, ТЗ §10.3/§15.1) — but
every request pays the full timeout before degrading. This module keeps a
tiny per-dependency failure counter so that after N consecutive failures
the dependency is *skipped* for a cool-off window instead of being retried
per query, saving the latency budget (§15.1).

Design notes:
- Pure in-process state; single-container deployment (matches cache design).
- Three states: closed → open → half_open → closed. In half_open one probe
  request is allowed through; its outcome decides the next state.
- Thread-safe via a plain lock; calls are O(1) and never raise.
"""

from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass, field


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, '') or default)
    except ValueError:
        return default


@dataclass
class _Breaker:
    threshold: int          # consecutive failures before opening
    reset_s: float          # cool-off window before half-open probe
    opened_at: float = 0.0
    failures: int = 0
    probing: bool = False   # one in-flight half-open probe at a time
    lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def allow(self) -> bool:
        """Whether a call may proceed (closed or a single half-open probe)."""
        with self.lock:
            if self.failures < self.threshold:
                return True
            now = time.time()
            if (now - self.opened_at) < self.reset_s:
                return False
            # Cool-off elapsed: admit exactly one probe request.
            if self.probing:
                return False
            self.probing = True
            self.opened_at = now  # re-arm window; failed probe re-opens immediately
            return True

    def record_success(self) -> None:
        with self.lock:
            self.failures = 0
            self.opened_at = 0.0
            self.probing = False

    def record_failure(self) -> None:
        with self.lock:
            self.probing = False
            self.failures += 1
            if self.failures >= self.threshold:
                self.opened_at = time.time()

    @property
    def state(self) -> str:
        with self.lock:
            if self.failures < self.threshold:
                return 'closed'
            if self.probing:
                return 'half_open'
            if (time.time() - self.opened_at) >= self.reset_s:
                return 'half_open'
            return 'open'


class CircuitBreakerRegistry:
    """Named breakers shared across the process."""

    def __init__(self, threshold: int | None = None, reset_s: float | None = None) -> None:
        self._threshold = threshold if threshold is not None else _env_int('ORCH_CB_THRESHOLD', 3)
        self._reset_s = reset_s if reset_s is not None else _env_int('ORCH_CB_RESET_S', 60)
        self._breakers: dict[str, _Breaker] = {}
        self._registry_lock = threading.Lock()

    def _get(self, name: str) -> _Breaker:
        with self._registry_lock:
            br = self._breakers.get(name)
            if br is None:
                br = _Breaker(threshold=self._threshold, reset_s=self._reset_s)
                self._breakers[name] = br
            return br

    def allow(self, name: str) -> bool:
        """False → skip the dependency entirely (degrade without waiting)."""
        return self._get(name).allow()

    def record_success(self, name: str) -> None:
        self._get(name).record_success()

    def record_failure(self, name: str) -> None:
        self._get(name).record_failure()

    def status(self) -> dict[str, str]:
        """Snapshot for /orchestrator/metrics (dependency health)."""
        with self._registry_lock:
            return {name: br.state for name, br in self._breakers.items()}


# Module-level singleton used by graph/native adapters.
registry = CircuitBreakerRegistry()
