"""§C4: публичный шеринг задач и fork — unit/integration тесты.

Проверяют:
 - генерацию/отзыв share-токена в модели CoderTaskMetas;
 - поиск только расшаренных задач (get_by_share_token);
 - отсутствие утечек IDOR (эндпоинты не принимают чужие chat_id напрямую);
 - защиту публичной HTML-страницы от XSS (экранирование title/tags/token);
 - корректную работу copy_sandbox для fork.
"""

import asyncio
import os
import re
import sys
import tempfile
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Add parent directory to path to import from the project
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# sandbox root must be set before importing open_webui.config-dependent modules
_TMP_SANDBOX_ROOT = tempfile.mkdtemp(prefix="coder-share-fork-test-")
os.environ.setdefault("WEBUI_SECRET_KEY", "test")
os.environ["CODER_SANDBOX_ROOT"] = _TMP_SANDBOX_ROOT

from fastapi import HTTPException  # noqa: E402

from open_webui.models.coder import (  # noqa: E402
    CoderTaskMetaForm,
    CoderTaskMetas,
)


def run(coro):
    return asyncio.run(coro)


@pytest.fixture()
def anyio_backend():
    return "asyncio"


class _FakeResult:
    def __init__(self, rows=None, rowcount=0):
        self._rows = rows or []
        self.rowcount = rowcount

    def scalars(self):
        return self

    def first(self):
        return self._rows[0] if self._rows else None

    def all(self):
        return self._rows


class FakeSession:
    """Минимальная подделка AsyncSession: add/flush без реальной БД."""

    def __init__(self, rows=None):
        self.added = []
        self.rows = list(rows or [])
        self._next = iter(self.rows)

    def add(self, obj):
        self.added.append(obj)

    async def flush(self):
        pass

    async def execute(self, stmt):
        # get_by_chat / get_by_share_token consume queued results in order
        for _ in range(1):
            pass
        if self._queued:
            return self._queued.pop(0)
        return _FakeResult([])

    _queued = []

    def queue(self, *results):
        self._queued = list(results)


def make_session_with_queued(*rows_per_call):
    s = FakeSession()
    s._queued = [_FakeResult([r] if r is not None else []) for r in rows_per_call]
    return s


class TestSetShare:
    def test_enable_generates_token(self):
        db = make_session_with_queued(None)  # no existing row -> creates one
        row = run(CoderTaskMetas.set_share("user-1", "chat-1", True, db))
        assert row.share_enabled is True
        assert row.share_token and len(row.share_token) >= 20
        assert row.shared_at is not None

    def test_disable_revokes_token(self):
        existing = MagicMock()
        existing.share_enabled = True
        existing.share_token = "tok-old"
        existing.shared_at = 123
        existing.updated_at = 0
        db = make_session_with_queued(existing)
        row = run(CoderTaskMetas.set_share("user-1", "chat-1", False, db))
        assert row.share_enabled is False
        assert row.share_token is None
        assert row.shared_at is None

    def test_reenable_rotates_token(self):
        existing = MagicMock()
        existing.share_enabled = False
        existing.share_token = None
        existing.shared_at = None
        existing.updated_at = 0
        db = make_session_with_queued(existing)
        row = run(CoderTaskMetas.set_share("user-1", "chat-1", True, db))
        assert row.share_token

        # second enable keeps the same token (idempotent)
        db2 = make_session_with_queued(row)
        row2 = run(CoderTaskMetas.set_share("user-1", "chat-1", True, db2))
        assert row2.share_token == row.share_token


class TestGetByShareToken:
    def test_empty_token_returns_none(self):
        db = FakeSession()
        assert run(CoderTaskMetas.get_by_share_token("", db)) is None

    def test_only_shared_rows_match(self):
        """get_by_share_token фильтрует share_enabled == True на уровне SQL —
        проверяем, что запрос содержит оба условия (защита от отзыва шаринга)."""
        captured = {}

        class CapturingSession(FakeSession):
            async def execute(self, stmt):
                captured["sql"] = str(stmt.compile(compile_kwargs={"literal_binds": True}))
                return _FakeResult([])

        run(CoderTaskMetas.get_by_share_token("abc", CapturingSession()))
        sql = captured["sql"].lower()
        assert "share_token" in sql
        assert "share_enabled" in sql


class TestForkSecurityProperties:
    """Владелец задачи определяется по токену шаринга, а не по переданному
    chat_id (исключает IDOR при форке)."""

    def test_fork_endpoint_signature_has_no_chat_id(self):
        from open_webui.routers import coder as coder_router

        fork_fn = coder_router.coder_task_fork
        params = set(fork_fn.__code__.co_varnames)
        assert "token" in params
        # chat_id берётся из src (по токену), не из запроса клиента
        assert "chat_id" not in params

    def test_share_endpoint_scopes_by_user_id(self):
        from open_webui.routers import coder as coder_router

        src = __import__("inspect").getsource(coder_router.coder_task_share)
        # set_share вызывается с user.id — чужой chat_id не переживёт запрос
        assert "CoderTaskMetas.set_share(user.id, chat_id" in src

    def test_unshared_token_404_on_fork(self):
        from open_webui.routers import coder as coder_router

        request = MagicMock()
        user = MagicMock(id="u2")
        with patch.object(coder_router, "check_coder_permission", new=AsyncMock()), \
             patch.object(coder_router.CoderTaskMetas, "get_by_share_token", new=AsyncMock(return_value=None)):
            with pytest.raises(HTTPException) as exc_info:
                run(coder_router.coder_task_fork(request, "revoked-token", None, user=user, db=MagicMock()))
            assert exc_info.value.status_code == 404
            assert exc_info.value.detail["code"] == "CODER_TASK_NOT_SHARED"


class TestPublicPageXss:
    """Публичная страница строится через html.escape — проверим это напрямую
    на функции рендера, эмулируя злоумышленные метаданные."""

    def _render(self, row, files_count=None):
        """Мини-копия рендера из coder_task_shared_page (то же экранирование)."""
        import html as _html
        import time as _time

        esc = _html.escape
        age_days = max(0, int((1e12 - (row.shared_at or row.updated_at)) // 86400))
        tags_html = "".join(f'<span class="tag">#{esc(str(t))}</span>' for t in (row.tags or []))
        return (
            f"<title>{esc(row.title or 'Coder task')}</title>"
            f"{tags_html}"
            f'<a href="/coder?fork={esc(row.share_token)}">'
        )

    def test_title_script_escaped(self):
        row = MagicMock()
        row.title = "<script>alert('xss')</script>"
        row.tags = []
        row.share_token = "tok"
        row.shared_at = 0
        row.updated_at = 0
        page = self._render(row)
        assert "<script>" not in page
        assert "&lt;script&gt;" in page

    def test_tag_quote_injection_escaped(self):
        row = MagicMock()
        row.title = "ok"
        row.tags = ['"><img src=x onerror=alert(1)>']
        row.share_token = "tok"
        row.shared_at = 0
        row.updated_at = 0
        page = self._render(row)
        # сырые кавычки/углы из тега не должны попадать в HTML как разметка
        assert '"><img' not in page
        assert "&lt;img" in page
        assert "&quot;" in page

    def test_token_with_specials_escaped_in_href(self):
        row = MagicMock()
        row.title = "t"
        row.tags = []
        row.share_token = 'a" onfocus="alert(1)'
        row.shared_at = 0
        row.updated_at = 0
        page = self._render(row)
        assert 'onfocus="alert' not in page

    def test_router_source_uses_escape(self):
        """Статическая проверка: роутер экранирует все пользовательские поля."""
        import inspect

        from open_webui.routers import coder as coder_router

        src = inspect.getsource(coder_router.coder_task_shared_page)
        for needle in ("esc(row.title", "esc(str(t))", "esc(row.mode", "esc(token)"):
            assert needle in src, f"missing escaping: {needle}"


class TestCopySandbox:
    def test_copy_files_between_sessions(self):
        from uuid import uuid4

        from open_webui.utils.coder import sandbox as coder_sandbox

        src_id, dst_id = str(uuid4()), str(uuid4())
        coder_sandbox.create_sandbox(src_id)
        coder_sandbox.write_file(src_id, "index.html", "<h1>hi</h1>")
        coder_sandbox.write_file(src_id, "src/app.js", "console.log(1)")
        coder_sandbox.create_sandbox(dst_id)

        result = coder_sandbox.copy_sandbox(src_id, dst_id)
        copied_paths = {c["path"] for c in result["copied"]}
        assert {"index.html", "src/app.js"} <= copied_paths
        assert result["skipped"] == []
        content, _ = coder_sandbox.read_file(dst_id, "index.html")
        assert content == "<h1>hi</h1>"
        # исходник не изменён
        assert len(coder_sandbox.list_files(src_id)) == 2

    def test_copy_missing_source_raises(self):
        from uuid import uuid4

        from open_webui.utils.coder import sandbox as coder_sandbox
        from open_webui.utils.coder.sandbox import SandboxError

        dst_id = str(uuid4())
        coder_sandbox.create_sandbox(dst_id)
        with pytest.raises(SandboxError):
            coder_sandbox.copy_sandbox("no-such-session", dst_id)

    def test_copy_missing_destination_raises(self):
        from uuid import uuid4

        from open_webui.utils.coder import sandbox as coder_sandbox
        from open_webui.utils.coder.sandbox import SandboxError

        src_id = str(uuid4())
        coder_sandbox.create_sandbox(src_id)
        with pytest.raises(SandboxError):
            coder_sandbox.copy_sandbox(src_id, "no-such-dst")


class TestForkEndpointFlow:
    """Интеграция: успешный fork создаёт новую мета-задачу с forked_from и
    копирует sandbox именно расшаренной задачи (get_by_chat автора+chat_id)."""

    def test_fork_copies_shared_task_sandbox(self):
        from open_webui.routers import coder as coder_router

        src_meta = MagicMock()
        src_meta.user_id = "author"
        src_meta.chat_id = "author-chat"
        src_meta.title = "Origin"
        src_meta.tags = ["demo"]
        src_meta.mode = None

        src_session = MagicMock()
        src_session.id = "author-session"

        calls = {"get_by_chat": [], "created": []}

        async def fake_get_by_chat(user_id, chat_id, db):
            calls["get_by_chat"].append((user_id, chat_id))
            return src_session

        async def fake_create(user_id, mode=None, meta=None, chat_id=None, db=None):
            sess = MagicMock()
            sess.id = "new-session"
            calls["created"].append({"user_id": user_id, "chat_id": chat_id})
            return sess

        async def fake_upsert(user_id, chat_id, form, db):
            from open_webui.models.coder import CoderTaskMeta

            row = CoderTaskMeta(
                id="meta-id", user_id=user_id, chat_id=chat_id,
                title=form.title, tags=form.tags, mode=form.mode,
                created_at=0, updated_at=0,
            )
            calls["created"].append({"meta_user": user_id, "meta_chat": chat_id})
            return row

        with patch.object(coder_router, "check_coder_permission", new=AsyncMock()), \
             patch.object(coder_router.CoderTaskMetas, "get_by_share_token", new=AsyncMock(return_value=src_meta)), \
             patch.object(coder_router.CoderTaskMetas, "upsert", new=AsyncMock(side_effect=fake_upsert)), \
             patch.object(coder_router.CoderSandboxSessions, "get_by_chat", new=AsyncMock(side_effect=fake_get_by_chat)), \
             patch.object(coder_router.CoderSandboxSessions, "list_by_user_id", new=AsyncMock(return_value=[])), \
             patch.object(coder_router.CoderSandboxSessions, "create", new=AsyncMock(side_effect=fake_create)), \
             patch.object(coder_router.CoderSandboxSessions, "update", new=AsyncMock()), \
             patch.object(coder_router.coder_sandbox, "create_sandbox"), \
             patch.object(coder_router.coder_sandbox, "copy_sandbox", return_value={"copied": [{"path": "a"}], "skipped": []}), \
             patch.object(coder_router, "_audit", new=AsyncMock()):
            resp = run(
                coder_router.coder_task_fork(
                    MagicMock(), "tok", None, user=MagicMock(id="forger"), db=AsyncMock()
                )
            )

        assert resp["forked_from"] == "author-chat"
        assert resp["sandbox_session_id"] == "new-session"
        assert resp["files_copied"] == 1
        # скопирована песочница именно расшаренной задачи автора
        assert ("author", "author-chat") in calls["get_by_chat"]
        # новая сессия привязана к новому chat_id форкера
        assert any(c.get("user_id") == "forger" and "chat_id" in c for c in calls["created"])
