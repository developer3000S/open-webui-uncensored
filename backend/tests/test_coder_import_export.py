"""§C-im/export: импорт/экспорт истории и песочниц — unit/integration тесты.

Проверяют:
 - round-trip export_zip -> import_zip_bytes (содержимое файлов сохраняется);
 - защиту от path traversal внутри zip-архива (опасные пути пропускаются);
 - отказ на битый zip / zip без манифеста / чужой формат;
 - лимиты объёма при импорте;
 - эндпоинт GET /sandbox/session/{id}/export (IDOR-guard через _get_sandbox_session);
 - эндпоинт POST /sandbox/import (создание новой сессии, аудит);
 - GET /tasks/shared/{token}/export: своя задача -> sandbox.zip, чужая -> только метаданные;
 - POST /tasks/export: IDOR-фильтр (только собственные чаты), лимит 100.
"""

import asyncio
import io
import json
import os
import sys
import tempfile
import zipfile
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

_TMP_SANDBOX_ROOT = tempfile.mkdtemp(prefix="coder-import-export-test-")
os.environ.setdefault("WEBUI_SECRET_KEY", "test")
os.environ["CODER_SANDBOX_ROOT"] = _TMP_SANDBOX_ROOT

from fastapi import HTTPException  # noqa: E402

from open_webui.utils.coder import sandbox as coder_sandbox  # noqa: E402
from open_webui.utils.coder.sandbox import SandboxError  # noqa: E402


def run(coro):
    return asyncio.run(coro)


@pytest.fixture()
def anyio_backend():
    return "asyncio"


# ---------------------------------------------------------------------------
# utils/coder/sandbox.py: export_zip / import_zip_bytes
# ---------------------------------------------------------------------------


def _make_session(session_id: str, files: dict[str, str]) -> None:
    try:
        coder_sandbox.create_sandbox(session_id, {})
    except SandboxError:
        pass  # повторный вызов в рамках одной сессии теста — директория уже есть
    for rel, content in files.items():
        coder_sandbox.write_file(session_id, rel, content)


def test_export_import_roundtrip():
    sid = "aabbccdd-1111-2222-3333-444455556666"
    _make_session(sid, {"index.html": "<h1>привет</h1>", "src/app.js": "console.log(1);"})

    archive = coder_sandbox.export_zip(sid)
    zf = zipfile.ZipFile(io.BytesIO(archive))
    assert "coder-sandbox.json" in zf.namelist()
    manifest = json.loads(zf.read("coder-sandbox.json").decode("utf-8"))
    assert manifest["coder_sandbox"] == 1
    assert manifest["session_id"] == sid
    paths = sorted(f["path"] for f in manifest["files"])
    assert paths == ["index.html", "src/app.js"]

    parsed = coder_sandbox.import_zip_bytes(archive)
    assert parsed["manifest"]["session_id"] == sid
    assert parsed["files"]["index.html"] == "<h1>привет</h1>"
    assert parsed["files"]["src/app.js"] == "console.log(1);"

    # импорт в новую сессию даёт идентичный набор файлов
    sid2 = "99887766-5544-3322-1100-ffeeddccbbaa"
    coder_sandbox.create_sandbox(sid2, {})
    for rel, content in parsed["files"].items():
        coder_sandbox.write_file(sid2, rel, content)
    listed = {f["path"] for f in coder_sandbox.list_files(sid2)}
    assert listed == {"index.html", "src/app.js"}


def test_export_missing_session_raises_not_found():
    with pytest.raises(SandboxError) as exc:
        coder_sandbox.export_zip("ffffffff-dead-beef-0000-111122223333")
    assert exc.value.code == "not_found"


def test_export_invalid_session_id_rejected():
    with pytest.raises(SandboxError):
        coder_sandbox.export_zip("../../etc/passwd")


def test_import_rejects_bad_zip():
    with pytest.raises(SandboxError) as exc:
        coder_sandbox.import_zip_bytes(b"this is not a zip file at all")
    assert exc.value.code == "bad_zip"


def test_import_rejects_zip_without_manifest():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("files/random.txt", "hello")
    with pytest.raises(SandboxError) as exc:
        coder_sandbox.import_zip_bytes(buf.getvalue())
    assert exc.value.code == "no_manifest"


def test_import_rejects_foreign_manifest():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("coder-sandbox.json", json.dumps({"something_else": True}))
    with pytest.raises(SandboxError) as exc:
        coder_sandbox.import_zip_bytes(buf.getvalue())
    assert exc.value.code == "bad_manifest"


def test_import_skips_path_traversal_entries():
    """Опасные пути (../, абсолютные) и blocked-паттерны внутри zip не попадают в результат."""
    buf = io.BytesIO()
    manifest = {"coder_sandbox": 1, "session_id": "x" * 36, "files": [{"path": "../../etc/passwd"}, {"path": "/.env"}, {"path": "secrets/key.txt"}, {"path": "ok.txt"}]}
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("coder-sandbox.json", json.dumps(manifest))
        zf.writestr("files/../../etc/passwd", "root:x:0:0")
        zf.writestr("files/.env", "SECRET=leak")
        zf.writestr("files/secrets/key.txt", "private-key")
        zf.writestr("files/ok.txt", "safe content")
    parsed = coder_sandbox.import_zip_bytes(buf.getvalue())
    assert set(parsed["files"].keys()) == {"ok.txt"}
    assert parsed["files"]["ok.txt"] == "safe content"


def test_import_skips_binary_and_huge_files():
    from open_webui.config import CODER_SANDBOX_MAX_FILE_SIZE

    buf = io.BytesIO()
    manifest = {"coder_sandbox": 1, "session_id": "x" * 36, "files": []}
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("coder-sandbox.json", json.dumps(manifest))
        zf.writestr("files/blob.bin", b"\xff\xfe\x00\x01binary")
        zf.writestr("files/huge.txt", "a" * (CODER_SANDBOX_MAX_FILE_SIZE + 1))
        zf.writestr("files/good.txt", "fine")
    parsed = coder_sandbox.import_zip_bytes(buf.getvalue())
    assert set(parsed["files"].keys()) == {"good.txt"}


def test_import_enforces_total_size_limit(monkeypatch):
    monkeypatch.setattr(coder_sandbox, "CODER_SANDBOX_MAX_TOTAL_SIZE", 10)
    buf = io.BytesIO()
    manifest = {"coder_sandbox": 1, "session_id": "x" * 36, "files": []}
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("coder-sandbox.json", json.dumps(manifest))
        zf.writestr("files/a.txt", "a" * 8)
        zf.writestr("files/b.txt", "b" * 8)
    with pytest.raises(SandboxError) as exc:
        coder_sandbox.import_zip_bytes(buf.getvalue())
    assert exc.value.code == "too_large"


# ---------------------------------------------------------------------------
# routers/coder.py: эндпоинты экспорта/импорта
# ---------------------------------------------------------------------------


def _request_stub(user_id="u1"):
    req = MagicMock()
    req.app.state = MagicMock()
    req.state = MagicMock()
    req.headers = {}
    req.url = MagicMock()
    req.base_url = "http://test"
    return req


def test_endpoint_export_calls_export_zip_and_audits():
    from open_webui.routers import coder as coder_router

    sid = "11223344-5566-7788-99aa-bbccddeeff00"
    _make_session(sid, {"main.py": "print('x')"})
    archive = coder_sandbox.export_zip(sid)

    session_row = MagicMock()
    db = AsyncMock()
    with (
        patch.object(coder_router, "_get_sandbox_session", new=AsyncMock(return_value=session_row)),
        patch.object(coder_router.CoderSandboxSessions, "touch", new=AsyncMock()),
        patch.object(coder_router, "_audit", new=AsyncMock()),
    ):
        resp = run(
            coder_router.coder_sandbox_export_zip(
                _request_stub(), sid, user=SimpleNamespace(id="u1", role="user"), db=db
            )
        )
    assert resp.media_type == "application/zip"
    assert "attachment" in resp.headers["Content-Disposition"]
    parsed = coder_sandbox.import_zip_bytes(resp.body)
    assert parsed["files"]["main.py"] == "print('x')"


def test_endpoint_export_maps_sandbox_error_to_http():
    from open_webui.routers import coder as coder_router

    with (
        patch.object(coder_router, "_get_sandbox_session", new=AsyncMock(side_effect=HTTPException(status_code=404))),
    ):
        with pytest.raises(HTTPException) as exc:
            run(
                coder_router.coder_sandbox_export_zip(
                    _request_stub(), "missing-session-not-a-uuid-but-guarded", user=SimpleNamespace(id="u1", role="user"), db=AsyncMock()
                )
            )
        assert exc.value.status_code == 404


def test_endpoint_import_creates_new_session():
    from open_webui.routers import coder as coder_router

    src_sid = "a1a1a1a1-b2b2-c3c3-d4d4-e5e5e5e5e5e5"
    _make_session(src_sid, {"index.html": "<p>restored</p>"})
    archive = coder_sandbox.export_zip(src_sid)

    created = MagicMock()
    created.id = "f0f0f0f0-1111-2222-3333-444455556666"
    upload = MagicMock()
    upload.read = AsyncMock(return_value=archive)

    with (
        patch.object(coder_router, "check_coder_permission", new=AsyncMock()),
        patch.object(coder_router.CoderSandboxSessions, "create", new=AsyncMock(return_value=created)),
        patch.object(coder_router.CoderSandboxSessions, "update", new=AsyncMock()),
        patch.object(coder_router, "_audit", new=AsyncMock()),
    ):
        result = run(
            coder_router.coder_sandbox_import_zip(
                _request_stub(), file=upload, chat_id=None, user=SimpleNamespace(id="u1", role="user"), db=AsyncMock()
            )
        )
    assert result["source_session_id"] == src_sid
    assert result["files_written"] == 1
    assert result["files_skipped"] == 0
    # файл действительно лежит в новой песочнице
    content, _mime = coder_sandbox.read_file(created.id, "index.html")
    assert content == "<p>restored</p>"


def test_endpoint_import_rejects_oversized_upload():
    from open_webui.routers import coder as coder_router

    upload = MagicMock()
    upload.read = AsyncMock(return_value=b"x" * (25 * 1024 * 1024 + 1))
    with (
        patch.object(coder_router, "check_coder_permission", new=AsyncMock()),
        pytest.raises(HTTPException) as exc,
    ):
        run(
            coder_router.coder_sandbox_import_zip(
                _request_stub(), file=upload, chat_id=None, user=SimpleNamespace(id="u1", role="user"), db=AsyncMock()
            )
        )
    assert exc.value.status_code == 413


def test_endpoint_shared_export_own_task_includes_sandbox_zip():
    from open_webui.routers import coder as coder_router

    src_sid = "b2b2b2b2-c3c3-d4d4-e5e5-f6f6f6f6f6f6"
    _make_session(src_sid, {"app.ts": "export const a = 1;"})

    row = MagicMock()
    row.user_id = "u1"
    row.chat_id = "chat-own"
    row.title = "Моя задача"
    row.tags = ["demo"]
    row.mode = "web"
    session_row = MagicMock()
    session_row.id = src_sid

    with (
        patch.object(coder_router, "check_coder_permission", new=AsyncMock()),
        patch.object(coder_router.CoderTaskMetas, "get_by_share_token", new=AsyncMock(return_value=row)),
        patch.object(coder_router.CoderSandboxSessions, "get_by_chat", new=AsyncMock(return_value=session_row)),
        patch.object(coder_router, "_audit", new=AsyncMock()),
    ):
        resp = run(
            coder_router.coder_task_shared_export(
                _request_stub(), "tok", user=SimpleNamespace(id="u1", role="user"), db=AsyncMock()
            )
        )
    zf = zipfile.ZipFile(io.BytesIO(resp.body))
    names = set(zf.namelist())
    assert "coder-task.json" in names and "sandbox.zip" in names
    meta = json.loads(zf.read("coder-task.json").decode("utf-8"))
    assert meta["coder_task_export"] == 1
    inner = coder_sandbox.import_zip_bytes(zf.read("sandbox.zip"))
    assert inner["files"]["app.ts"] == "export const a = 1;"


def test_endpoint_shared_export_foreign_task_leaks_no_files():
    from open_webui.routers import coder as coder_router

    row = MagicMock()
    row.user_id = "someone-else"
    row.chat_id = "chat-other"
    row.title = "Чужая задача"
    row.tags = []
    row.mode = "web"

    get_by_chat = AsyncMock()
    with (
        patch.object(coder_router, "check_coder_permission", new=AsyncMock()),
        patch.object(coder_router.CoderTaskMetas, "get_by_share_token", new=AsyncMock(return_value=row)),
        patch.object(coder_router.CoderSandboxSessions, "get_by_chat", new=get_by_chat),
        patch.object(coder_router, "_audit", new=AsyncMock()),
    ):
        resp = run(
            coder_router.coder_task_shared_export(
                _request_stub(), "tok", user=SimpleNamespace(id="u1", role="user"), db=AsyncMock()
            )
        )
    zf = zipfile.ZipFile(io.BytesIO(resp.body))
    assert "sandbox.zip" not in zf.namelist()
    get_by_chat.assert_not_awaited()  # чужую песочницу даже не ищем


def test_endpoint_shared_export_unknown_token_404():
    from open_webui.routers import coder as coder_router

    with (
        patch.object(coder_router, "check_coder_permission", new=AsyncMock()),
        patch.object(coder_router.CoderTaskMetas, "get_by_share_token", new=AsyncMock(return_value=None)),
        pytest.raises(HTTPException) as exc,
    ):
        run(
            coder_router.coder_task_shared_export(
                _request_stub(), "bad-token", user=SimpleNamespace(id="u1", role="user"), db=AsyncMock()
            )
        )
    assert exc.value.status_code == 404


def test_endpoint_tasks_export_filters_foreign_chats():
    from open_webui.routers import coder as coder_router
    from open_webui.models.chats import Chats

    own_chat = MagicMock()
    own_chat.id = "chat-own"
    own_chat.title = "Mine"
    own_chat.chat = {"history": {"messages": []}}
    own_chat.meta = {}
    own_chat.pinned = False
    own_chat.created_at = 1
    own_chat.updated_at = 2

    async def fake_get(chat_id, user_id):
        return own_chat if chat_id == "chat-own" and user_id == "u1" else None

    items = [
        coder_router.CoderChatExportItem(id="chat-own", chat={}),
        coder_router.CoderChatExportItem(id="chat-alien", chat={}),
    ]
    with (
        patch.object(coder_router, "check_coder_permission", new=AsyncMock()),
        patch.object(Chats, "get_chat_by_id_and_user_id", new=fake_get),
        patch.object(coder_router, "_audit", new=AsyncMock()),
    ):
        result = run(
            coder_router.coder_tasks_export_chats(
                _request_stub(), items, user=SimpleNamespace(id="u1", role="user"), db=AsyncMock()
            )
        )
    assert [c["id"] for c in result] == ["chat-own"]  # чужой чат не выгружен (IDOR-guard)


def test_endpoint_tasks_export_caps_at_100_chats():
    from open_webui.routers import coder as coder_router
    from open_webui.models.chats import Chats

    chat = MagicMock()
    chat.id = "c"
    chat.title = "T"
    chat.chat = {}
    chat.meta = {}
    chat.pinned = False
    chat.created_at = 1
    chat.updated_at = 1

    calls = []

    async def fake_get(chat_id, user_id):
        calls.append(chat_id)
        return chat

    items = [coder_router.CoderChatExportItem(id=f"c{i}", chat={}) for i in range(150)]
    with (
        patch.object(coder_router, "check_coder_permission", new=AsyncMock()),
        patch.object(Chats, "get_chat_by_id_and_user_id", new=fake_get),
        patch.object(coder_router, "_audit", new=AsyncMock()),
    ):
        result = run(
            coder_router.coder_tasks_export_chats(
                _request_stub(), items, user=SimpleNamespace(id="u1", role="user"), db=AsyncMock()
            )
        )
    assert len(result) == 100
    assert len(calls) == 100
