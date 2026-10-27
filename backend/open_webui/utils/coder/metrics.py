"""Prometheus metrics for the Coder section (§14.2).

Counters/histograms named ``coder_*``. If the ``prometheus_client`` package is
not installed, a no-op shim keeps the instrumentation sites unchanged so the
application runs without the optional dependency.
"""

import logging

log = logging.getLogger(__name__)

try:
    from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram, generate_latest

    _AVAILABLE = True
except ImportError:  # pragma: no cover - optional dependency
    _AVAILABLE = False
    log.debug('prometheus_client not installed; coder metrics are disabled')


class _NoopMetric:
    def labels(self, *args, **kwargs):
        return self

    def inc(self, *args, **kwargs):
        pass

    def dec(self, *args, **kwargs):
        pass

    def observe(self, *args, **kwargs):
        pass

    def set(self, *args, **kwargs):
        pass


_NOOP = _NoopMetric()

if _AVAILABLE:
    CODER_REGISTRY = CollectorRegistry()

    CODER_REQUESTS_TOTAL = Counter(
        'coder_requests_total',
        'Total Coder API requests',
        ['endpoint', 'method', 'status'],
        registry=CODER_REGISTRY,
    )
    CODER_GITHUB_REQUESTS_TOTAL = Counter(
        'coder_github_requests_total',
        'GitHub API requests made by the Coder section',
        ['method', 'status', 'retried'],
        registry=CODER_REGISTRY,
    )
    CODER_EXPORT_JOBS_TOTAL = Counter(
        'coder_export_jobs_total',
        'Coder export jobs by terminal status',
        ['status'],
        registry=CODER_REGISTRY,
    )
    CODER_EXPORT_DURATION_SECONDS = Histogram(
        'coder_export_duration_seconds',
        'Duration of Coder export jobs in seconds',
        buckets=(0.5, 1, 2.5, 5, 10, 30, 60, 120, 300),
        registry=CODER_REGISTRY,
    )
    CODER_AUDIT_EVENTS_TOTAL = Counter(
        'coder_audit_events_total',
        'Coder audit events recorded',
        ['action'],
        registry=CODER_REGISTRY,
    )
    CODER_ACTIVE_CONNECTIONS = Gauge(
        'coder_github_connections',
        'Number of connected GitHub accounts (observed on /github/connection checks)',
        registry=CODER_REGISTRY,
    )
    CODER_RATE_LIMITED_TOTAL = Counter(
        'coder_rate_limited_total',
        'Requests rejected/deferred due to rate limiting',
        ['scope'],
        registry=CODER_REGISTRY,
    )
else:  # pragma: no cover
    CODER_REGISTRY = None
    CODER_REQUESTS_TOTAL = _NOOP
    CODER_GITHUB_REQUESTS_TOTAL = _NOOP
    CODER_EXPORT_JOBS_TOTAL = _NOOP
    CODER_EXPORT_DURATION_SECONDS = _NOOP
    CODER_AUDIT_EVENTS_TOTAL = _NOOP
    CODER_ACTIVE_CONNECTIONS = _NOOP
    CODER_RATE_LIMITED_TOTAL = _NOOP


def observe_github_request(method: str, status: int, retried: bool = False, error: str | None = None) -> None:
    """Record one GitHub API call outcome."""
    if not _AVAILABLE:
        return
    label_status = str(status or 0)
    if error:
        label_status = f'{label_status}_{error.lower()}'[:60]
    try:
        CODER_GITHUB_REQUESTS_TOTAL.labels(method=method.upper(), status=label_status, retried=str(bool(retried)).lower()).inc()
    except Exception:  # pragma: no cover
        log.debug('coder metrics: github request observe failed', exc_info=True)


def observe_export_job(status: str, duration_seconds: float | None = None) -> None:
    if not _AVAILABLE:
        return
    try:
        CODER_EXPORT_JOBS_TOTAL.labels(status=status).inc()
        if duration_seconds is not None:
            CODER_EXPORT_DURATION_SECONDS.observe(duration_seconds)
    except Exception:  # pragma: no cover
        log.debug('coder metrics: export job observe failed', exc_info=True)


def observe_audit_event(action: str) -> None:
    if not _AVAILABLE:
        return
    try:
        CODER_AUDIT_EVENTS_TOTAL.labels(action=action).inc()
    except Exception:  # pragma: no cover
        log.debug('coder metrics: audit observe failed', exc_info=True)


def render_metrics() -> bytes:
    """Expose the coder registry in Prometheus text format (empty when disabled)."""
    if not _AVAILABLE or CODER_REGISTRY is None:
        return b'# prometheus_client not installed\n'
    return generate_latest(CODER_REGISTRY)
