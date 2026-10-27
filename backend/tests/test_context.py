"""Tests for automatic model context-window detection and request trimming.

A request that is bigger than the model's context window is rejected by the
engine (`request (N tokens) exceeds the available context size`), so the
assembled payload is trimmed before it is sent.  The trim has a prescribed
order — compact the history, then drop the tool definitions, then drop the
oldest messages — and must never drop the system prompt or the final user
turn.  Detection has to work for studio (llama.cpp `meta.n_ctx`), Ollama
(`model_info.<arch>.context_length` / `details.context_length`) and external
connections (admin-configured `api_config.context_length`).

Run: python3 backend/tests/test_context.py
"""

import asyncio
import os
import sys
import unittest
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

# Importing open_webui.config requires a secret key; tests run without the
# normal startup script, so seed one before anything pulls the config in.
os.environ.setdefault('WEBUI_SECRET_KEY', 'test-context-key')

try:
    from open_webui.utils.context import (
        MAX_CONTEXT_LIMIT,
        estimate_request_tokens,
        get_model_context_length,
        get_prompt_token_budget,
        trim_request_to_context,
    )
except ModuleNotFoundError as exc:  # pragma: no cover - host without deps
    raise SystemExit(
        f'skip: this test needs the application dependencies ({exc.name}). '
        'Run it inside the container or in an installed venv.'
    )


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------


def studio_model(n_ctx=4096, n_ctx_train=32768):
    """A model entry for a Studio (llama.cpp) connection, as merged by the API."""
    return {
        'id': 'Dark-Science-12B',
        'owned_by': 'openai',
        'openai': {
            'id': 'Dark-Science-12B',
            'meta': {'n_ctx': n_ctx, 'n_ctx_train': n_ctx_train},
        },
    }


def ollama_model(context_length=32768, details_context=None):
    """A model entry for an Ollama connection, as built by utils/models.py."""
    details = {'context_length': details_context if details_context is not None else context_length}
    return {
        'id': 'qwen3.5:0.8b',
        'owned_by': 'ollama',
        'ollama': {
            'model_info': {'qwen35.context_length': context_length},
            'details': details,
        },
    }


class TestDetection(unittest.TestCase):
    """get_model_context_length: precedence and source coverage."""

    def test_unknown_context_returns_none(self):
        self.assertIsNone(get_model_context_length({}))
        self.assertIsNone(get_model_context_length(None))
        self.assertIsNone(get_model_context_length({'id': 'x'}))

    def test_zero_and_garbage_advertisements_are_ignored(self):
        self.assertIsNone(get_model_context_length(studio_model(n_ctx=0, n_ctx_train=0)))
        self.assertIsNone(
            get_model_context_length({'ollama': {'details': {'context_length': 'nope'}}})
        )

    def test_studio_loaded_ctx_beats_trained_ctx(self):
        # The engine was started with 4096 even though the model trains at 32768;
        # the request must be planned against the window that is actually loaded.
        self.assertEqual(get_model_context_length(studio_model(n_ctx=4096, n_ctx_train=32768)), 4096)

    def test_studio_falls_back_to_trained_ctx(self):
        self.assertEqual(get_model_context_length(studio_model(n_ctx=0, n_ctx_train=32768)), 32768)

    def test_ollama_model_info_is_read(self):
        self.assertEqual(get_model_context_length(ollama_model(context_length=32768)), 32768)

    def test_ollama_clamped_to_guard_rail(self):
        clamped = get_model_context_length(ollama_model(context_length=1_000_000))
        self.assertEqual(clamped, MAX_CONTEXT_LIMIT)

    def test_per_model_override_beats_engine(self):
        # An admin override on the model record wins over what the engine reports.
        model = studio_model(n_ctx=4096)
        model['info'] = {'params': {'context_length': 16384}}
        self.assertEqual(get_model_context_length(model), 16384)

        model = ollama_model(context_length=32768)
        model['info'] = {'meta': {'context_length': 8192}}
        self.assertEqual(get_model_context_length(model), 8192)

    def test_api_config_beats_engine(self):
        # External gateways advertise nothing usable, so the connection-level
        # config is the only signal — and it also wins over engine values.
        model = studio_model(n_ctx=4096)
        model['api_config'] = {'context_length': 16384}
        self.assertEqual(get_model_context_length(model), 16384)

    def test_per_model_override_beats_api_config(self):
        model = studio_model(n_ctx=4096)
        model['api_config'] = {'context_length': 16384}
        model['info'] = {'params': {'context_length': 8192}}
        self.assertEqual(get_model_context_length(model), 8192)

    def test_top_level_field_is_read(self):
        # Merged models publish the window on the record itself; presets
        # inherit their base model's window there.  Detection must see it.
        self.assertEqual(get_model_context_length({'id': 'x', 'context_length': 32768}), 32768)

    def test_api_config_beats_top_level_field(self):
        # A per-connection override outranks the value published on the record.
        model = {'id': 'x', 'context_length': 32768, 'api_config': {'context_length': 8192}}
        self.assertEqual(get_model_context_length(model), 8192)

    def test_engine_value_beats_record_field(self):
        # The record's own value is only a hint: the engine was started with
        # a smaller window than the record advertises, and the request must be
        # planned against the window that is actually loaded.
        model = studio_model(n_ctx=4096)
        model['context_length'] = 32768
        self.assertEqual(get_model_context_length(model), 4096)

    def test_record_field_used_when_engine_is_silent(self):
        # External gateways advertise nothing usable, so the record's value
        # (copied from the connection config or a preset) is the fallback.
        model = {'id': 'external-model', 'context_length': 32768}
        self.assertEqual(get_model_context_length(model), 32768)

    def test_budget_reserves_completion_tokens(self):
        model = studio_model(n_ctx=4096)
        self.assertEqual(get_prompt_token_budget(model), 4096 - 512)

    def test_budget_none_when_context_unknown(self):
        self.assertIsNone(get_prompt_token_budget({}))


# ---------------------------------------------------------------------------
# Estimation
# ---------------------------------------------------------------------------


def user(text):
    return {'role': 'user', 'content': text}


def assistant(text):
    return {'role': 'assistant', 'content': text}


def tool(name, description='a tool', parameters=None):
    return {
        'type': 'function',
        'function': {
            'name': name,
            'description': description,
            'parameters': parameters or {'type': 'object', 'properties': {}},
        },
    }


class TestEstimation(unittest.TestCase):
    def test_empty_request_is_zero(self):
        self.assertEqual(estimate_request_tokens({}), 0)

    def test_messages_are_counted(self):
        payload = {'messages': [user('hello there'), assistant('hi back')]}
        self.assertGreater(estimate_request_tokens(payload), 0)

    def test_longer_message_costs_more(self):
        short = estimate_request_tokens({'messages': [user('hi')]})
        long_ = estimate_request_tokens({'messages': [user('hi ' * 200)]})
        self.assertGreater(long_, short)

    def test_tools_are_counted(self):
        without = estimate_request_tokens({'messages': [user('hi')]})
        with_tools = estimate_request_tokens({'messages': [user('hi')], 'tools': [tool('search')]})
        self.assertGreater(with_tools, without)

    def test_non_message_context_is_counted(self):
        base = estimate_request_tokens({'messages': [user('hi')]})
        payload = {
            'messages': [user('hi')],
            'system': 'You are helpful.',
            'context': 'some RAG context',
            'knowledge': 'some knowledge',
        }
        self.assertGreater(estimate_request_tokens(payload), base)


# ---------------------------------------------------------------------------
# Trimming
# ---------------------------------------------------------------------------


class NoCompaction:
    """Stub compact_messages_for_request that always reports 'disabled'."""

    @staticmethod
    async def compact(*args, **kwargs):
        return [], None, False


class FailingCompaction:
    """A compaction backend that raises — the trim must still proceed."""

    @staticmethod
    async def compact(*args, **kwargs):
        raise RuntimeError('compaction backend is down')


def budget_of(limit):
    return {'info': {'params': {'context_length': limit}}}


def run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


class TestTrimming(unittest.TestCase):
    def test_unknown_context_leaves_payload_untouched(self):
        payload = {'messages': [user('hi ' * 500)]}
        before = estimate_request_tokens(payload)
        result = run(trim_request_to_context(payload, {}))
        self.assertEqual(estimate_request_tokens(result), before)

    def test_payload_under_budget_is_untouched(self):
        payload = {'messages': [user('hi')], 'tools': [tool('search')]}
        model = budget_of(65536)
        messages_before = len(payload['messages'])
        result = run(trim_request_to_context(payload, model))
        self.assertEqual(len(result['messages']), messages_before)
        self.assertEqual(len(result.get('tools') or []), 1)

    def test_tools_dropped_before_history(self):
        # 4096-token budget: the tools alone fit, the history pushes it over.
        payload = {
            'messages': [user(f'turn {i} ' * 400) for i in range(8)],
            'tools': [tool(f'tool_{i}', 'x' * 200) for i in range(4)],
        }
        model = budget_of(4096)
        result = run(trim_request_to_context(payload, model, compact=NoCompaction.compact))
        self.assertNotIn('tools', result)
        self.assertGreater(len(result['messages']), 1)

    def test_oldest_messages_dropped_last(self):
        payload = {
            'messages': [user(f'turn {i} ' * 400) for i in range(8)],
            'tools': [],
        }
        model = budget_of(4096)
        result = run(trim_request_to_context(payload, model, compact=NoCompaction.compact))
        self.assertLessEqual(estimate_request_tokens(result), 4096 - 512)
        # The newest turn survives.
        self.assertIn('turn 7', str(result['messages'][-1]))

    def test_system_prompt_and_last_user_are_never_dropped(self):
        payload = {
            'messages': [
                {'role': 'system', 'content': 'system prompt ' * 100},
                user('first turn ' * 400),
                user('second turn ' * 400),
                user('the latest turn'),
            ],
        }
        model = budget_of(4096)
        result = run(trim_request_to_context(payload, model, compact=NoCompaction.compact))

        roles = [m['role'] for m in result['messages']]
        self.assertEqual(roles[0], 'system')
        self.assertEqual(roles[-1], 'user')
        self.assertEqual(result['messages'][-1]['content'], 'the latest turn')

    def test_two_messages_are_never_trimmed(self):
        payload = {'messages': [{'role': 'system', 'content': 's'}, user('only turn')]}
        model = budget_of(1024)
        result = run(trim_request_to_context(payload, model, compact=NoCompaction.compact))
        self.assertEqual(len(result['messages']), 2)

    def test_compaction_runs_before_dropping_tools(self):
        """Compaction is step 1; when it frees enough, tools survive."""
        calls = {'compacted': False}

        async def compact(request, user, messages, metadata, model_id, models, system_prompt):
            calls['compacted'] = True
            # Halve the history and report success.
            return [{'role': 'system', 'content': 'summary'}], 'compacted summary', True

        payload = {
            'messages': [user(f'turn {i} ' * 400) for i in range(10)],
            'tools': [tool('search', 'x' * 100)],
        }
        model = budget_of(8192)
        result = run(trim_request_to_context(payload, model, compact=compact))

        self.assertTrue(calls['compacted'])
        # Compaction replaced the history with a summary, so the tools survive.
        self.assertEqual(len(result.get('tools') or []), 1)

    def test_compaction_failure_is_non_fatal(self):
        payload = {
            'messages': [user(f'turn {i} ' * 400) for i in range(6)],
            'tools': [tool('search', 'x' * 100)],
        }
        model = budget_of(4096)
        result = run(trim_request_to_context(payload, model, compact=FailingCompaction.compact))
        # Still trimmed, just without the compaction step.
        self.assertNotIn('tools', result)
        self.assertGreater(len(result['messages']), 1)


if __name__ == '__main__':
    unittest.main(verbosity=2)
