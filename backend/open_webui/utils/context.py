"""Automatic model context-window detection.

Context limits come from different places depending on where a model lives:

  * OpenAI connections backed by llama.cpp (the Studio) advertise the loaded
    context in `meta.n_ctx` and the context the model was trained for in
    `meta.n_ctx_train` on `/v1/models`.
  * Ollama reports the training context length in
    `model_info.<arch>.context_length` (reachable via `/api/show`).
  * Everything else (external OpenAI-compatible gateways, cloud providers)
    rarely reports anything usable on `/v1/models`, so the limit has to come
    from the admin's per-model or per-connection configuration.

The effective limit is always the loaded context (what the engine can
actually hold right now), never the training context.  Models are routinely
loaded with a smaller window than they were trained for.
"""

import json
import logging
import sys
import threading

from open_webui.env import GLOBAL_LOG_LEVEL
from open_webui.utils.misc import add_or_update_system_message, get_content_from_message, get_system_message

log = logging.getLogger(__name__)
logging.basicConfig(stream=sys.stdout, level=GLOBAL_LOG_LEVEL)

# Guard rail: even when a provider advertises a huge window, we never plan a
# request larger than this.  Keeps a broken/lying provider from turning into
# an out-of-memory event on a local engine.
MAX_CONTEXT_LIMIT = 131072

# Assumed tokens reserved for the model's reply when budgeting the prompt.
# Engines reject `max_tokens` larger than the remaining window, and a
# zero-completion budget makes the prompt budget effectively the whole ctx.
RESERVED_COMPLETION_TOKENS = 512

_MODEL_INFO_KEY_CACHE: dict[str, str] = {}

_CONTEXT_LENGTH_KEYS = (
    'context_length',
    'max_context_length',
    'context_window',
    'max_context_window',
    'max_input_tokens',
    'max_tokens',
)


def _coerce_positive_int(value) -> int | None:
    """Best-effort int coercion; returns None for anything unusable."""
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _extract_context_length(model_info: dict) -> int | None:
    """Read `model_info.<arch>.context_length` (Ollama `/api/show`)."""
    if not isinstance(model_info, dict):
        return None

    for key, value in model_info.items():
        if not isinstance(key, str) or not key.endswith(_CONTEXT_LENGTH_KEYS):
            continue

        # Prefer an explicit "max input" hint when present: some adapters
        # report both a trained window and a smaller usable input window.
        for preferred in ('max_input_tokens', 'max_context_length', 'max_context_window', 'context_window'):
            if key.endswith(preferred):
                parsed = _coerce_positive_int(value)
                if parsed:
                    return parsed

        parsed = _coerce_positive_int(value)
        if parsed:
            return parsed

    return None


def _extract_meta_context(meta: dict) -> int | None:
    """Read `meta.n_ctx` / `meta.n_ctx_train` (llama.cpp `/v1/models`)."""
    if not isinstance(meta, dict):
        return None

    n_ctx = _coerce_positive_int(meta.get('n_ctx'))
    if n_ctx:
        return n_ctx

    return _coerce_positive_int(meta.get('n_ctx_train'))


def _extract_kv_context(model: dict) -> int | None:
    """Read the context length from flat/loosely-typed model entries."""
    if not isinstance(model, dict):
        return None

    for key, value in model.items():
        if not isinstance(key, str) or not key.endswith(_CONTEXT_LENGTH_KEYS):
            continue
        parsed = _coerce_positive_int(value)
        if parsed:
            return parsed

    return None


def _clamp_context(limit: int | None) -> int | None:
    if limit is None:
        return None
    return max(512, min(limit, MAX_CONTEXT_LIMIT))


def get_model_context_length(model: dict) -> int | None:
    """Resolve the context window (in tokens) a model can currently hold.

    Precedence (highest first):
      1. An explicit limit set on the Open WebUI model record itself.
      2. An explicit limit configured on the connection (`context_length`).
      3. The engine's live advertised window (llama.cpp `meta.n_ctx`,
         Ollama `model_info.<arch>.context_length`) — the window the engine
         was actually started with, so it outranks any stale record value.
      4. The value published on the model record, which is what the UI
         displays: merged OpenAI models carry the engine advertisement here
         and presets inherit their base model's window.

    Returns None when nothing is known — callers must treat that as "no
    information" and fall back to their existing behaviour rather than
    assuming an unlimited window.
    """
    if not isinstance(model, dict):
        return None

    info = model.get('info') or {}

    # 1. Per-model override (admin UI / custom model params).
    info_params = info.get('params') or {}
    info_meta = info.get('meta') or {}
    for source in (info_params, info_meta):
        limit = _extract_kv_context(source)
        if limit:
            return _clamp_context(limit)

    # 2. Per-connection override (api_config.context_length).
    limit = _extract_kv_context(model.get('api_config') or {})
    if limit:
        return _clamp_context(limit)

    # 3. What the engine advertises.
    openai_model = model.get('openai') or {}
    ollama_model = model.get('ollama') or {}

    # llama.cpp: `meta.n_ctx` is the window the engine was started with.
    meta = openai_model.get('meta')
    if isinstance(meta, dict):
        limit = _extract_meta_context(meta)
        if limit:
            return _clamp_context(limit)

    # Ollama: the trained window from the GGUF, surfaced by `/api/show`.
    model_info = ollama_model.get('model_info') or ollama_model.get('modelInfo') or {}
    limit = _extract_context_length(model_info)
    if limit:
        return _clamp_context(limit)

    # Some Ollama builds expose the same value under `details`.
    details = ollama_model.get('details')
    if isinstance(details, dict):
        limit = _extract_kv_context(details)
        if limit:
            return _clamp_context(limit)

    # Studio connection: the /v1/models payload carries llama.cpp meta as well.
    if not isinstance(meta, dict):
        limit = _extract_meta_context(openai_model)
        if limit:
            return _clamp_context(limit)

    # 4. The record's own published value — a hint that is only reached when
    # the engine advertised nothing (external gateways) or the record was
    # built away from the live engine (presets).
    limit = _extract_kv_context(model)
    if limit:
        return _clamp_context(limit)

    return None


def get_context_limit(model: dict) -> int | None:
    """Public alias used by the trimming path."""
    return get_model_context_length(model)


def get_prompt_token_budget(model: dict, reserved: int = RESERVED_COMPLETION_TOKENS) -> int | None:
    """Maximum number of prompt tokens a request to this model may carry.

    Returns None when the context window is unknown, in which case the
    caller should not trim (no information to trim against).
    """
    limit = get_context_limit(model)
    if limit is None:
        return None

    reserved = max(0, min(reserved, limit - 256))
    return max(0, limit - reserved)


# ---------------------------------------------------------------------------
# Token estimation
# ---------------------------------------------------------------------------

_ENCODER = None
_ENCODER_LOCK = threading.Lock()


def _get_encoder():
    """Return a cl100k_base encoder, or None when tiktoken is unavailable.

    A dedicated BPE tokenizer is only needed for the trim decision, which is
    a rare, slow path; the cheap heuristic is fine everywhere else.
    """
    global _ENCODER
    if _ENCODER is not None:
        return _ENCODER

    with _ENCODER_LOCK:
        if _ENCODER is None:
            try:
                import tiktoken

                _ENCODER = tiktoken.get_encoding('cl100k_base')
            except Exception:
                _ENCODER = False

    return _ENCODER or None


def _text_tokens(text) -> int:
    if text is None:
        return 0
    if not isinstance(text, str):
        try:
            text = json.dumps(text, ensure_ascii=False)
        except Exception:
            text = str(text)
    if not text:
        return 0

    encoder = _get_encoder()
    if encoder is None:
        return max(1, len(text) // 4)
    try:
        return len(encoder.encode(text, disallowed_special=()))
    except Exception:
        return max(1, len(text) // 4)


def _message_tokens(message: dict) -> int:
    """Estimate one chat message, including tool calls and images."""
    if not isinstance(message, dict):
        return _text_tokens(message)

    total = 4  # role/content framing overhead per message
    content = message.get('content')

    if isinstance(content, list):
        for item in content:
            if not isinstance(item, dict):
                total += _text_tokens(item)
            elif item.get('type') in ('image', 'image_url'):
                total += 1000
            else:
                total += _text_tokens(item.get('text') or item.get('image_url') or item.get('content') or '')
    else:
        total += _text_tokens(content)

    total += _text_tokens(message.get('output'))
    total += _text_tokens(message.get('tool_calls'))
    total += _text_tokens(message.get('files'))
    return total


def estimate_request_tokens(form_data: dict) -> int:
    """Estimate the prompt-token cost of a complete request payload.

    Covers the message list, the tool definitions, and everything else that
    is sent to the engine and consumes context (system prompt, RAG sources,
    knowledge, model params) — an under-estimate here means a 400 later.
    """
    if not isinstance(form_data, dict):
        return 0

    total = 0
    for message in form_data.get('messages') or []:
        total += _message_tokens(message)

    for tool in form_data.get('tools') or []:
        if isinstance(tool, dict) and 'function' in tool:
            total += _text_tokens(tool['function'])
        else:
            total += _text_tokens(tool)

    # Non-message fields that are part of the request and consume context.
    for key in ('system', 'prompt', 'context', 'knowledge', 'sources'):
        total += _text_tokens(form_data.get(key))

    params = form_data.get('params')
    if isinstance(params, dict):
        total += _text_tokens(params.get('system'))

    return total


# ---------------------------------------------------------------------------
# Trimming
# ---------------------------------------------------------------------------

# The last user turn is what the model is replying to — dropping it changes
# the meaning of the request, so it is never trimmed.
_MIN_KEPT_MESSAGES = 2


def _protected_indices(messages: list) -> set:
    """Indices of messages that must survive any trim.

    The system prompt(s) and the final user turn together carry the request's
    intent; removing them would leave the engine with nothing coherent to answer.
    """
    protected = {i for i, msg in enumerate(messages) if isinstance(msg, dict) and msg.get('role') == 'system'}

    for i in range(len(messages) - 1, -1, -1):
        msg = messages[i]
        if isinstance(msg, dict) and msg.get('role') == 'user':
            protected.add(i)
            break

    return protected


def _trim_messages(messages: list, budget: int) -> list:
    """Drop the oldest unprotected messages until the list fits `budget`."""
    if len(messages) <= _MIN_KEPT_MESSAGES:
        return messages

    protected = _protected_indices(messages)
    unprotected = [i for i in range(len(messages)) if i not in protected]

    # If nothing is trimmable, hand the request back unchanged so the engine
    # can report the overflow honestly instead of us silently emptying it.
    if not unprotected:
        return messages

    costs = [_message_tokens(msg) for msg in messages]
    total = sum(costs)

    dropped = set()
    while total > budget and unprotected:
        index = unprotected.pop(0)
        dropped.add(index)
        total -= costs[index]

    # Nothing was trimmable to begin with — hand the request back unchanged so
    # the engine can report the overflow honestly instead of us emptying it.
    if not dropped:
        return messages

    return [msg for i, msg in enumerate(messages) if i not in dropped]


def _estimate_list_tokens(*lists) -> int:
    return sum(_message_tokens(msg) for lst in lists for msg in lst)


def _drop_tools(form_data: dict) -> bool:
    """Remove tool definitions from the payload. Returns True if dropped."""
    if form_data.get('tools'):
        del form_data['tools']
        return True
    return False


async def trim_request_to_context(
    form_data: dict,
    model: dict,
    request=None,
    user=None,
    metadata: dict | None = None,
    compact=None,
) -> dict:
    """Trim an assembled request payload so it fits the model's context.

    Order matters and is deliberate (per the project's requirement):
      1. compact the chat history — keeps the most information per token,
      2. drop tool definitions — tools are conveniences, history is meaning,
      3. drop the oldest messages — last resort, keeps system + last user.

    `compact` is `compact_messages_for_request` from context_compaction; kept
    as a parameter so the module stays import-light and testable.

    The payload is modified in place and also returned.
    """
    budget = get_prompt_token_budget(model)
    if budget is None:
        # Unknown window — nothing to trim against, leave the request alone.
        return form_data

    if estimate_request_tokens(form_data) <= budget:
        return form_data

    context_length = get_model_context_length(model) or 0
    model_id = form_data.get('model') or (model.get('id') if isinstance(model, dict) else 'unknown')

    log.info(
        'Context trim required: model=%s context=%d budget=%d estimated=%d',
        model_id,
        context_length,
        budget,
        estimate_request_tokens(form_data),
    )

    # --- 1. History compaction -------------------------------------------------
    if compact is not None:
        messages = form_data.get('messages') or []
        system_message = get_system_message(messages)
        system_prompt = get_content_from_message(system_message) if system_message else ''

        models = None
        if request is not None:
            models = getattr(request.app.state, 'MODELS', None)
        if models is None and isinstance(model, dict):
            models = {model.get('id'): model}

        try:
            compacted_messages, summary, did_compact = await compact(
                request,
                user,
                messages,
                metadata or {},
                model_id,
                models or {},
                system_prompt,
            )
            if did_compact and summary:
                form_data['messages'] = add_or_update_system_message(
                    f'[CONVERSATION SUMMARY]\n{summary}', compacted_messages, append=True
                )
            elif did_compact:
                form_data['messages'] = compacted_messages
        except Exception:
            log.exception('Context-aware compaction failed; continuing with manual trim')

    # --- 2. Drop tools ---------------------------------------------------------
    if estimate_request_tokens(form_data) > budget:
        if _drop_tools(form_data):
            log.info('Context trim: dropped tools for model=%s', model_id)

    # --- 3. Drop oldest messages ----------------------------------------------
    if estimate_request_tokens(form_data) > budget:
        form_data['messages'] = _trim_messages(form_data.get('messages') or [], budget)
        log.info(
            'Context trim: dropped oldest messages for model=%s remaining=%d',
            model_id,
            len(form_data.get('messages') or []),
        )

    final = estimate_request_tokens(form_data)
    if final > budget:
        log.warning(
            'Context trim: request still exceeds budget for model=%s budget=%d estimated=%d',
            model_id,
            budget,
            final,
        )
    else:
        log.info('Context trim complete: model=%s estimated=%d budget=%d', model_id, final, budget)

    return form_data
