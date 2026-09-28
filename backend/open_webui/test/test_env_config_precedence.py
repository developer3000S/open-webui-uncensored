"""Tests for the .env-over-stored-row precedence in open_webui/models/config.py.

The config table outranks everything else at read time, which is why a fixed code
default never reached an existing install: the stale row kept winning. These tests
drive the real Config class against a throwaway SQLite table and check what each
reader returns once .env declares a key.

models/config.py imports get_async_db by name, so that is the symbol patched here.
Leaving it alone would point the assertions at the deployment's own webui.db, and
test_saving_a_bound_key would write through to it.

Needs the application's dependencies (sqlalchemy, aiosqlite), so on a bare host the
module exits early; run it wherever the app itself runs:
    python3 backend/open_webui/test/test_env_config_precedence.py
"""

import asyncio
import os
import tempfile
import unittest
from contextlib import asynccontextmanager
from pathlib import Path
from unittest import mock

try:
    from open_webui.internal.db import Base
    from open_webui.models import config as config_module
    from open_webui.models.config import Config
    from open_webui.utils import env_config
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from sqlalchemy.pool import NullPool
except ModuleNotFoundError as exc:  # pragma: no cover - host without deps
    raise SystemExit(
        f'skip: this test needs the application dependencies ({exc.name}). '
        'Run it inside the container or in an installed venv.'
    )

DB_FILE = Path(tempfile.mkdtemp(prefix='env-config-test-')) / 'test.db'
engine = create_async_engine(f'sqlite+aiosqlite:///{DB_FILE}', poolclass=NullPool)
Session = async_sessionmaker(engine, expire_on_commit=False)


@asynccontextmanager
async def _test_db():
    async with Session() as session:
        try:
            yield session
        finally:
            await session.close()


DEFAULTS = {
    'rag.embedding_batch_size': 1,
    'rag.embedding_model': 'qwen3-embedding:0.6b',
    'rag.reranking_engine': 'external',
    'ui.analysis_model': 'gpt-4',
}

# Values deliberately different from DEFAULTS, as a seeded install's rows are.
STORED = {
    'rag.embedding_batch_size': 32,
    'rag.embedding_model': 'stale/model-from-early-deploy',
    'ui.analysis_model': 'admin-ui-picked-model',
}


async def _seed_table():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    async with Session() as session:
        for key, value in STORED.items():
            session.add(Config(key=key, value=value, updated_at=0))
        await session.commit()


async def _stored_value(key):
    async with Session() as session:
        row = await session.get(Config, key)
        return None if row is None else row.value


class EnvPrecedenceTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        Config.configure(defaults=dict(DEFAULTS), enable_persistent=True)

    @classmethod
    def tearDownClass(cls) -> None:
        asyncio.run(engine.dispose())

    def setUp(self) -> None:
        env_config.reset_declared()
        self.addCleanup(env_config.reset_declared)
        asyncio.run(_seed_table())
        patcher = mock.patch.object(config_module, 'get_async_db', _test_db)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_stored_row_wins_while_env_is_silent(self) -> None:
        """Baseline: with no declarations nothing changes, so the mechanism is opt-in."""
        self.assertEqual(asyncio.run(Config.get('rag.embedding_batch_size')), 32)

    def test_declared_name_outranks_the_stored_row(self) -> None:
        env_config.record_declared({'RAG_EMBEDDING_BATCH_SIZE'})
        self.assertEqual(asyncio.run(Config.get('rag.embedding_batch_size')), 1)

    def test_undeclared_sibling_still_reads_the_table(self) -> None:
        """Binding one key must not switch the whole table off."""
        env_config.record_declared({'RAG_EMBEDDING_BATCH_SIZE'})
        self.assertEqual(
            asyncio.run(Config.get('rag.embedding_model')),
            'stale/model-from-early-deploy',
        )

    def test_inherited_environment_without_the_file_does_not_bind(self) -> None:
        """The image bakes RAG_EMBEDDING_MODEL for its build-time model download.

        If os.environ alone bound the key, that baked-in value would override the
        admin UI's choice in every deploy that never mentioned the setting.
        """
        os.environ['RAG_EMBEDDING_MODEL'] = 'sentence-transformers/all-MiniLM-L6-v2'
        self.addCleanup(os.environ.pop, 'RAG_EMBEDDING_MODEL', None)
        self.assertEqual(
            asyncio.run(Config.get('rag.embedding_model')),
            'stale/model-from-early-deploy',
        )

    def test_get_many_mixes_bound_and_stored_keys(self) -> None:
        env_config.record_declared({'RAG_EMBEDDING_BATCH_SIZE'})
        values = asyncio.run(Config.get_many('rag.embedding_batch_size', 'rag.embedding_model', 'ui.analysis_model'))
        self.assertEqual(
            values,
            {
                'rag.embedding_batch_size': 1,
                'rag.embedding_model': 'stale/model-from-early-deploy',
                'ui.analysis_model': 'admin-ui-picked-model',
            },
        )

    def test_get_namespace_reports_the_bound_value(self) -> None:
        """A namespace reader that showed the row would tell the admin one thing while
        the code used another."""
        env_config.record_declared({'RAG_EMBEDDING_BATCH_SIZE', 'RAG_EMBEDDING_MODEL'})
        values = asyncio.run(Config.get_namespace('rag'))
        self.assertEqual(values['rag.embedding_batch_size'], 1)
        self.assertEqual(values['rag.embedding_model'], 'qwen3-embedding:0.6b')
        self.assertNotIn('ui.analysis_model', values)

    def test_get_all_reports_the_effective_config(self) -> None:
        env_config.record_declared({'RAG_EMBEDDING_BATCH_SIZE'})
        values = asyncio.run(Config.get_all())
        self.assertEqual(values['rag.embedding_batch_size'], 1)
        self.assertEqual(values['rag.embedding_model'], 'stale/model-from-early-deploy')
        self.assertEqual(values['ui.analysis_model'], 'admin-ui-picked-model')

    def test_saving_a_bound_key_updates_the_running_value_not_the_row(self) -> None:
        """A row for a bound key can never be read back, so writing it would store a
        value that differs from the live one -- the confusion this layer removes."""
        env_config.record_declared({'UI_ANALYSIS_MODEL'})
        asyncio.run(Config.upsert({'ui.analysis_model': 'changed-in-admin-ui'}))
        self.assertEqual(Config.default_value('ui.analysis_model'), 'changed-in-admin-ui')
        self.assertEqual(asyncio.run(Config.get('ui.analysis_model')), 'changed-in-admin-ui')
        self.assertEqual(asyncio.run(_stored_value('ui.analysis_model')), 'admin-ui-picked-model')

    def test_saving_an_unbound_key_still_reaches_the_table(self) -> None:
        """Guard for the same edit: only bound keys bypass the write."""
        asyncio.run(Config.upsert({'ui.analysis_model': 'changed-in-admin-ui'}))
        self.assertEqual(asyncio.run(_stored_value('ui.analysis_model')), 'changed-in-admin-ui')

    def test_seed_defaults_adds_the_full_default_set(self) -> None:
        """Unbound keys keep the insert-if-missing behaviour the admin UI relies on."""
        asyncio.run(Config.seed_defaults(DEFAULTS))
        self.assertEqual(asyncio.run(Config.get('rag.reranking_engine')), 'external')
        self.assertEqual(asyncio.run(_stored_value('rag.embedding_batch_size')), 32, 'existing row kept')

    def test_seed_defaults_skips_bound_keys(self) -> None:
        """With a bound key seeded, a future row would silently disagree with .env."""
        env_config.record_declared({'RAG_RERANKING_ENGINE'})
        asyncio.run(Config.seed_defaults(DEFAULTS))
        self.assertIsNone(asyncio.run(_stored_value('rag.reranking_engine')))

    def test_bound_key_absent_from_defaults_still_reads_the_row(self) -> None:
        """env_bound requires the key to be registered, so a stray name in .env cannot
        make its config key read as None."""
        env_config.record_declared({'NOT_A_CONFIG_KEY'})
        self.assertEqual(asyncio.run(Config.get('ui.analysis_model')), 'admin-ui-picked-model')


if __name__ == '__main__':
    unittest.main(verbosity=2)
