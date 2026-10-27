"""Business-level OpenTelemetry metrics for Open WebUI.

HTTP-level metrics (request counts / durations) live in ``metrics.py``.
This module adds *application-domain* instruments so operators can watch
what actually matters for an LLM product:

* webui.llm.requests (counter)            – completions requested
* webui.llm.errors (counter)              – failed completions
* webui.llm.tokens (counter)              – prompt/completion tokens consumed
* webui.llm.duration (histogram, seconds) – end-to-end completion latency
* webui.retrieval.documents (histogram)   – docs returned per RAG query
* webui.retrieval.duration (histogram)    – time spent collecting context

All helpers are **no-ops when OTel is disabled** (``ENABLE_OTEL`` false or
the instruments were never initialised), so importing this module on the
hot path costs a single boolean check and is always safe.

Attribute cardinality is deliberately bounded: only model/provider ids,
streaming flag, error class and token type are used as labels — never
user ids, chat ids or message content.
"""

from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger(__name__)

# Populated by init_business_metrics() from main.py's OTel bootstrap.
# Left as None when telemetry is off -> every record_* helper short-circuits.
_llm_requests_counter = None
_llm_errors_counter = None
_llm_tokens_counter = None
_llm_duration_histogram = None
_retrieval_documents_histogram = None
_retrieval_duration_histogram = None


def _get_meter():
    """Return the global OTel meter, or None if the API isn't available."""
    try:
        from opentelemetry import metrics

        return metrics.get_meter('open_webui.telemetry.business')
    except Exception:  # pragma: no cover - opentelemetry not installed
        return None


def init_business_metrics() -> bool:
    """Create business instruments on the global meter provider.

    Safe to call multiple times; returns True when instruments are active.
    """
    global _llm_requests_counter, _llm_errors_counter, _llm_tokens_counter
    global _llm_duration_histogram, _retrieval_documents_histogram, _retrieval_duration_histogram

    if _llm_requests_counter is not None:
        return True

    meter = _get_meter()
    if meter is None:
        return False

    try:
        _llm_requests_counter = meter.create_counter(
            name='webui.llm.requests',
            description='Number of LLM completion requests.',
            unit='1',
        )
        _llm_errors_counter = meter.create_counter(
            name='webui.llm.errors',
            description='Number of failed LLM completion requests.',
            unit='1',
        )
        _llm_tokens_counter = meter.create_counter(
            name='webui.llm.tokens',
            description='Tokens consumed by LLM completions, by type.',
            unit='token',
        )
        _llm_duration_histogram = meter.create_histogram(
            name='webui.llm.duration',
            description='End-to-end duration of LLM completion requests.',
            unit='s',
        )
        _retrieval_documents_histogram = meter.create_histogram(
            name='webui.retrieval.documents',
            description='Number of documents collected per retrieval request.',
            unit='1',
        )
        _retrieval_duration_histogram = meter.create_histogram(
            name='webui.retrieval.duration',
            description='Time spent collecting retrieval context.',
            unit='s',
        )
    except Exception:
        log.debug('Failed to initialise business metrics', exc_info=True)
        return False

    log.info('Open WebUI business metrics initialised')
    return True


def _provider_from_id(model_id: Any) -> str:
    """Coarse, low-cardinality provider label derived from a model id."""
    if not model_id:
        return 'unknown'
    model_id = str(model_id)
    if ':' in model_id:
        return model_id.split(':', 1)[0]
    if model_id.startswith('gpt') or model_id.startswith('o'):
        return 'openai'
    return 'other'


# ---------------------------------------------------------------------------
# Recording helpers (all no-ops when telemetry is disabled)
# ---------------------------------------------------------------------------


def record_llm_request(model_id: Any, stream: bool = False) -> None:
    if _llm_requests_counter is None:
        return
    try:
        _llm_requests_counter.add(
            1,
            {
                'model': str(model_id or 'unknown'),
                'provider': _provider_from_id(model_id),
                'stream': bool(stream),
            },
        )
    except Exception:  # never break the request path for telemetry
        log.debug('record_llm_request failed', exc_info=True)


def record_llm_error(model_id: Any, error: BaseException | None = None) -> None:
    if _llm_errors_counter is None:
        return
    try:
        _llm_errors_counter.add(
            1,
            {
                'model': str(model_id or 'unknown'),
                'provider': _provider_from_id(model_id),
                'error_type': type(error).__name__ if error else 'Unknown',
            },
        )
    except Exception:
        log.debug('record_llm_error failed', exc_info=True)


def record_llm_usage(model_id: Any, usage: dict | None) -> None:
    """Record token usage from an OpenAI-style response ``usage`` block."""
    if _llm_tokens_counter is None or not isinstance(usage, dict):
        return
    try:
        common = {'model': str(model_id or 'unknown'), 'provider': _provider_from_id(model_id)}
        prompt_tokens = usage.get('prompt_tokens') or 0
        completion_tokens = usage.get('completion_tokens') or 0
        if prompt_tokens:
            _llm_tokens_counter.add(int(prompt_tokens), {**common, 'type': 'prompt'})
        if completion_tokens:
            _llm_tokens_counter.add(int(completion_tokens), {**common, 'type': 'completion'})
        # Optional extra dimensions when the provider reports them.
        details = usage.get('prompt_tokens_details') or {}
        cached = details.get('cached_tokens') or 0
        if cached:
            _llm_tokens_counter.add(int(cached), {**common, 'type': 'cached'})
    except Exception:
        log.debug('record_llm_usage failed', exc_info=True)


def record_llm_duration(model_id: Any, duration_seconds: float, stream: bool = False) -> None:
    if _llm_duration_histogram is None:
        return
    try:
        _llm_duration_histogram.record(
            max(duration_seconds, 0.0),
            {
                'model': str(model_id or 'unknown'),
                'provider': _provider_from_id(model_id),
                'stream': bool(stream),
            },
        )
    except Exception:
        log.debug('record_llm_duration failed', exc_info=True)


def record_retrieval(doc_count: int, duration_seconds: float | None = None) -> None:
    if _retrieval_documents_histogram is None:
        return
    try:
        _retrieval_documents_histogram.record(max(int(doc_count), 0))
        if duration_seconds is not None and _retrieval_duration_histogram is not None:
            _retrieval_duration_histogram.record(max(float(duration_seconds), 0.0))
    except Exception:
        log.debug('record_retrieval failed', exc_info=True)
