"""Tests for the Ollama keep_alive normalisation in open_webui/config.py.

Ollama parses a string keep_alive as a Go duration, so the value .env carries has to reach
the API as an int when it is unitless: sending "7200" gets HTTP 400 'missing unit in
duration', which surfaces as a failed upload rather than a slow one. A bare number in .env
is the obvious thing an operator writes, so the conversion is asserted here.

Needs the application's dependencies (config.py imports the app's env module), so on a bare
host the module exits early; run it wherever the app itself runs:
    python3 backend/open_webui/test/test_embedding_keep_alive.py
"""

import importlib.util
import unittest

try:
    from open_webui import config as app_config
    from open_webui.config import RAG_EMBEDDING_IDLE_TIMEOUT, _ollama_keep_alive
except ModuleNotFoundError as exc:  # pragma: no cover - host without deps
    raise SystemExit(
        f'skip: this test needs the application dependencies ({exc.name}). '
        'Run it inside the container or in an installed venv.'
    )


class OllamaKeepAliveTest(unittest.TestCase):
    def test_unitless_number_becomes_int_seconds(self) -> None:
        """A string '7200' is rejected by Ollama; the int 7200 means seconds."""
        self.assertEqual(_ollama_keep_alive('7200'), 7200)
        self.assertIsInstance(_ollama_keep_alive('7200'), int)

    def test_negative_int_never_evicts(self) -> None:
        self.assertEqual(_ollama_keep_alive('-1'), -1)

    def test_go_duration_stays_a_string(self) -> None:
        self.assertEqual(_ollama_keep_alive('30m'), '30m')

    def test_surrounding_whitespace_is_stripped(self) -> None:
        self.assertEqual(_ollama_keep_alive('  120  '), 120)

    def test_unset_falls_back_to_the_idle_timeout(self) -> None:
        """Not asking Ollama at all means its 5-minute default, which evicts the weights
        between files and makes the next request pay a full model reload."""
        for raw in (None, '', '   '):
            with self.subTest(raw=raw):
                self.assertEqual(_ollama_keep_alive(raw), RAG_EMBEDDING_IDLE_TIMEOUT)

    def test_module_constant_is_api_safe(self) -> None:
        """Whatever .env says, the exported constant must be a form Ollama accepts:
        an int, or a string carrying a unit."""
        value = app_config.RAG_EMBEDDING_KEEP_ALIVE
        if isinstance(value, str):
            self.assertNotEqual(value.strip(), '')
            self.assertTrue(
                any(value.strip().endswith(unit) for unit in ('ns', 'us', 'ms', 's', 'm', 'h')),
                f'{value!r} would be rejected as "missing unit in duration"',
            )


class EmbeddingPayloadTest(unittest.TestCase):
    def test_ollama_requests_carry_keep_alive(self) -> None:
        """Without it the daemon applies its own default and the model is reloaded
        between files."""
        source = importlib.util.find_spec('open_webui.retrieval.utils')
        with open(source.origin, encoding='utf-8') as file:
            text = file.read()
        for function in ('def generate_ollama_batch_embeddings', 'def agenerate_ollama_batch_embeddings'):
            with self.subTest(function=function):
                body = text.split(function, 1)[1].split('\ndef ', 1)[0]
                self.assertIn("'keep_alive': RAG_EMBEDDING_KEEP_ALIVE", body)


if __name__ == '__main__':
    unittest.main(verbosity=2)
