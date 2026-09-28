"""Tests for open_webui/utils/env_config.py.

Loaded by file path rather than imported as `open_webui.utils.*` so these run on a bare
host without the application's dependencies (`open_webui/__init__.py` imports typer).

Run with either:
    python3 -m unittest discover -s backend/open_webui/utils -p 'test_*.py'
    cd backend && pytest open_webui/utils/test_env_config.py
"""

import importlib.util
import re
import shlex
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

_SPEC = importlib.util.spec_from_file_location('env_config', str(Path(__file__).resolve().parent / 'env_config.py'))
env_config = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(env_config)

_ENV_TEXT = """\
# comment
OLLAMA_BASE_URL='http://host.docker.internal:11434'

  RAG_EMBEDDING_BATCH_SIZE=1   # inline comment
export VECTOR_DB=chroma
EMPTY_ON_PURPOSE=
NOT_AN_ASSIGNMENT
"""


class ParseEnvFileTest(unittest.TestCase):
    def test_returns_names_with_unquoted_values(self) -> None:
        values = env_config.parse_env_file(_ENV_TEXT)
        self.assertEqual(
            values,
            {
                'OLLAMA_BASE_URL': 'http://host.docker.internal:11434',
                'RAG_EMBEDDING_BATCH_SIZE': '1',
                'VECTOR_DB': 'chroma',
                'EMPTY_ON_PURPOSE': '',
            },
        )

    def test_declared_key_with_empty_value_still_counts(self) -> None:
        """ "KEY=" is an explicit statement the setting is empty, not an absence."""
        self.assertIn('EMPTY_ON_PURPOSE', env_config.parse_env_file('EMPTY_ON_PURPOSE=\n'))

    def test_keeps_spaces_inside_quotes(self) -> None:
        """A reranker model id is stored with a trailing space; quotes must not eat it."""
        parsed = env_config.parse_env_file("M='qllama/bge:latest '\n")
        self.assertEqual(parsed['M'], 'qllama/bge:latest ')

    def test_docker_env_file_quoting_is_normalised(self) -> None:
        """`docker run --env-file` leaves the quotes in the value, compose strips them."""
        self.assertEqual(env_config.unquote("'http://x:11434'"), env_config.unquote('http://x:11434'))

    def test_later_line_wins(self) -> None:
        self.assertEqual(env_config.parse_env_file('A=1\nA=2\n'), {'A': '2'})


class DeclaredNamesTest(unittest.TestCase):
    def setUp(self) -> None:
        env_config.reset_declared()
        self.addCleanup(env_config.reset_declared)

    def test_env_bound_requires_the_name_to_be_declared(self) -> None:
        self.assertFalse(env_config.is_declared_in_env('rag.embedding_batch_size'))
        env_config.record_declared({'RAG_EMBEDDING_BATCH_SIZE'})
        self.assertTrue(env_config.is_declared_in_env('rag.embedding_batch_size'))
        self.assertFalse(env_config.is_declared_in_env('rag.embedding_model'))

    def test_env_name_for_maps_dotted_keys(self) -> None:
        self.assertEqual(env_config.env_name_for('rag.embedding_batch_size'), 'RAG_EMBEDDING_BATCH_SIZE')

    def test_read_env_file_records_and_reports_names(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / '.env'
            path.write_text(_ENV_TEXT, encoding='utf-8')
            names = env_config.read_env_file(path)
        self.assertIn('OLLAMA_BASE_URL', names)
        self.assertTrue(env_config.is_declared_in_env('rag.embedding_batch_size'))

    def test_missing_file_declares_nothing(self) -> None:
        self.assertEqual(env_config.read_env_file(Path('/nonexistent/dir/.env')), set())
        env_config.record_declared({'A'})
        env_config.read_env_file(Path('/nonexistent/dir/.env'))
        self.assertEqual(env_config.declared_names(), frozenset({'A'}))


class EnvBoundIsNotInheritedEnvironmentTest(unittest.TestCase):
    def test_inherited_image_env_does_not_bind_a_key(self) -> None:
        """The image ships RAG_EMBEDDING_MODEL for the build-time model download. If merely
        having it in os.environ bound the config key, that baked-in value would override
        whatever the admin saved -- the exact failure this distinction prevents."""
        env_config.reset_declared()
        self.addCleanup(env_config.reset_declared)
        with mock.patch.dict('os.environ', {'RAG_EMBEDDING_MODEL': 'sentence-transformers/all-MiniLM-L6-v2'}):
            self.assertFalse(env_config.is_declared_in_env('rag.embedding_model'))


class ShellExportSafetyTest(unittest.TestCase):
    """backend/start.sh feeds parse_env_file() output into generated `export K=...`
    statements. Two consumers of one file (the shell launcher and env.py) must not
    disagree, so the shape the shell relies on is asserted instead of left implicit.
    """

    def test_names_are_valid_shell_identifiers(self) -> None:
        for name in env_config.parse_env_file(_ENV_TEXT):
            self.assertTrue(re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', name), name)

    def test_values_never_contain_newlines(self) -> None:
        """A newline would break out of the export statement it is interpolated into."""
        for value in env_config.parse_env_file(_ENV_TEXT).values():
            self.assertNotIn('\n', value)

    def test_metacharacters_survive_a_sh_round_trip(self) -> None:
        """Values are passed through unexpanded and re-quoted, never eval'd: a payload
        that looks like a command must arrive as literal text."""
        nasty = "a b; echo pwned | wc -c `id` $(id) 'q' * $HOME"
        values = env_config.parse_env_file(f'SHELL_UNSAFE="{nasty}"\n')
        statement = ''.join(f'export {k}={shlex.quote(v)}\n' for k, v in values.items())
        result = subprocess.run(
            ['sh', '-c', f'{statement}printf "%s" "$SHELL_UNSAFE"'],
            capture_output=True,
            text=True,
            check=True,
        )
        self.assertEqual(result.stdout, nasty)


class EnvNameAliasesMatchConfigPyTest(unittest.TestCase):
    """ENV_NAME_ALIASES is the handshake between "name in .env" and "name config.py reads".

    config.py builds DEFAULT_CONFIG from constants like ENABLE_WEB_SEARCH, while
    env_name_for() derives WEB_SEARCH_ENABLE from the dotted key. The derived name is
    what the deployment actually writes, so without the alias the two never match and
    a stale SQLite row wins silently. Regenerating the mapping from config.py catches
    drift: a key fixed upstream, or a new one added, either needs an entry here or
    must already resolve by the derived name.
    """

    CONFIG_PY = Path(__file__).resolve().parents[1] / 'config.py'

    @classmethod
    def _expected_aliases(cls):
        import ast

        tree = ast.parse(cls.CONFIG_PY.read_text(encoding='utf-8'))

        def getenv_names(node):
            names = []
            for n in ast.walk(node):
                if not isinstance(n, ast.Call):
                    continue
                func = n.func
                qualified = f'{func.value.id}.{func.attr}' if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name) else None
                if qualified in ('os.getenv', 'os.environ.get') and n.args:
                    arg = n.args[0]
                    if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                        names.append(arg.value)
            return names

        # var -> env names read by any assignment to it, including the try/except blocks
        var_env: dict[str, list[str]] = {}
        # var -> other var, for `VAR = other` passthroughs whose real getenv sits elsewhere
        var_alias: dict[str, str] = {}
        for node in ast.walk(tree):
            if not isinstance(node, ast.Assign):
                continue
            names = getenv_names(node.value)
            if names:
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        var_env[target.id] = names
            elif isinstance(node.value, ast.Name):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        var_alias[target.id] = node.value.id

        def resolved_env_names(var, seen=None):
            seen = seen or set()
            if var in seen:
                return []
            seen.add(var)
            if var in var_env:
                return var_env[var]
            if var in var_alias:
                return resolved_env_names(var_alias[var], seen)
            return []

        literal = None
        for node in tree.body:
            if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == 'DEFAULT_CONFIG' for t in node.targets
            ):
                literal = node.value
                break
        assert literal is not None, 'DEFAULT_CONFIG literal not found in config.py'

        entries = [
            (k.value, v.id)
            for k, v in zip(literal.keys, literal.values)
            if isinstance(k, ast.Constant) and isinstance(k.value, str) and isinstance(v, ast.Name)
        ]

        expected = {}
        for key, var in entries:
            derived = key.upper().replace('.', '_')
            names = resolved_env_names(var)
            if not names:
                continue
            distinct = list(dict.fromkeys(names))
            if derived in distinct:
                continue
            # A default composed of several env vars has no single owner: the key stays
            # derived-name-bound, and setting any one of them in .env would otherwise
            # disable persistence for the whole group.
            if len(distinct) == 1:
                expected[derived] = distinct[0]
        return expected

    def test_table_matches_the_mapping_config_py_implies(self):
        expected = self._expected_aliases()
        actual = dict(env_config.ENV_NAME_ALIASES)
        self.assertEqual(actual, expected, msg='\n'.join(self._diff(expected, actual)))

    def test_aliases_are_not_self_mappings(self):
        """An entry pointing at its own derived name is dead weight and a sign of a
        copy-paste error in the table."""
        for derived, actual in env_config.ENV_NAME_ALIASES.items():
            self.assertNotEqual(derived, actual)

    def test_aliases_cover_the_legacy_flag_names_this_deploy_uses(self):
        """The specific names .env pins here; if the alias for one disappears, the
        deployment's setting quietly stops applying again."""
        for name in ('ENABLE_WEB_SEARCH', 'DEFAULT_MODEL_METADATA', 'ENABLE_CODE_INTERPRETER', 'ENABLE_NOTES', 'ENABLE_CALENDAR', 'ENABLE_AUTOMATIONS', 'ENABLE_CHANNELS'):
            self.assertIn(name, env_config.ENV_NAME_ALIASES.values(), name)

    @staticmethod
    def _diff(expected, actual):
        only_expected = set(expected) - set(actual)
        only_actual = set(actual) - set(expected)
        changed = {k for k in expected.keys() & actual.keys() if expected[k] != actual[k]}
        lines = []
        if only_expected:
            lines.append(f'missing from ENV_NAME_ALIASES ({len(only_expected)}):')
            lines.extend(f'  {k} -> {expected[k]}' for k in sorted(only_expected))
        if only_actual:
            lines.append(f'no longer implied by config.py ({len(only_actual)}):')
            lines.extend(f'  {k} -> {actual[k]}' for k in sorted(only_actual))
        if changed:
            lines.append(f'changed mapping ({len(changed)}):')
            lines.extend(f'  {k}: expected {expected[k]}, have {actual[k]}' for k in sorted(changed))
        return lines or ['ENV_NAME_ALIASES is out of sync with config.py']


class ParityWithDotenvTest(unittest.TestCase):
    """env.py loads the file through python-dotenv while start.sh uses this parser.

    Two readers of one file must not disagree, and the corpus is exactly the syntax
    the real .env uses, so drift in either direction is caught here. Skipped where
    python-dotenv is not installed.
    """

    CORPUS = """\
# a comment
OLLAMA_BASE_URL='http://host.docker.internal:11434'
OPENAI_API_KEY=example-not-a-real-key
CORS_ALLOW_ORIGIN='*'
FORWARDED_ALLOW_IPS='*'
RAG_EMBEDDING_BATCH_SIZE=1   # inline comment
RAG_EMBEDDING_MODEL="qwen3-embedding:0.6b"
RAG_RERANKING_MODEL='qllama/bge-reranker-v2-m3:latest'
EMPTY_ON_PURPOSE=
TRANSFORMERS_NO_ADVISORY_WARNINGS=1
"""

    @classmethod
    def setUpClass(cls) -> None:
        try:
            from dotenv import dotenv_values
        except ModuleNotFoundError:
            raise unittest.SkipTest('python-dotenv not installed on this host')
        cls.dotenv_values = staticmethod(dotenv_values)

    def test_same_values_as_python_dotenv(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / '.env'
            path.write_text(self.CORPUS, encoding='utf-8')
            reference = {k: v for k, v in self.dotenv_values(path).items() if v is not None}
        self.assertEqual(env_config.parse_env_file(self.CORPUS), reference)

    def test_every_name_declared_by_dotenv_is_declared_here(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / '.env'
            path.write_text(self.CORPUS, encoding='utf-8')
            reference = set(self.dotenv_values(path))
        self.assertEqual(set(env_config.parse_env_file(self.CORPUS)), reference)


if __name__ == '__main__':
    unittest.main()
