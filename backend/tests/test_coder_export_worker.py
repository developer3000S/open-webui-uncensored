"""GitHub export regression tests (async worker path).

Root cause of the broken export: utils/coder/export_worker.py imported the
non-existent ``_execute_export_job`` from routers/coder.py, so every job with
CODER_ASYNC_EXPORT=True failed with ImportError before touching GitHub.

These tests (mock GitHub API, no network) verify:
 - ``_execute_export_job`` exists and runs the full Git Data API sequence
   (push-permission check -> ref -> blobs -> tree -> commit -> branch -> PR);
 - the background worker path persists a terminal ``completed`` status;
 - missing write access fails fast with CODER_FORBIDDEN.
"""

import asyncio
import os
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("WEBUI_SECRET_KEY", "test")

from open_webui.routers import coder as coder_router  # noqa: E402
from open_webui.utils.coder import export_worker  # noqa: E402


def run(coro):
    return asyncio.run(coro)


FORM = {
    "owner": "acme",
    "repo": "widgets",
    "base_branch": "main",
    "branch": "coder/feature",
    "commit_message": "feat: add widget",
    "files": [{"action": "update", "path": "w.py", "content": "print(1)"}],
    "host": None,
}


def _resp(status_code=200, payload=None):
    r = MagicMock()
    r.status_code = status_code
    r.json.return_value = payload if payload is not None else {}
    return r


def _client_mocks(branch_exists=False):
    """Patch GitHubClient + github_request used inside _execute_export_job.

    First get_ref call = base branch (always returns 'base-sha'); second call =
    working-branch lookup — succeeds when the branch exists, otherwise raises
    CODER_NOT_FOUND like the real client does.
    """
    if branch_exists:
        get_ref = AsyncMock(side_effect=["base-sha", "old-sha"])
    else:
        from open_webui.utils.coder.github_client import GitHubAPIError

        get_ref = AsyncMock(side_effect=["base-sha", GitHubAPIError("CODER_NOT_FOUND", "Not Found", 404)])
    mocks = {
        "get_ref_commit_sha": get_ref,
        "create_blob": AsyncMock(return_value="blob-sha"),
        "create_tree": AsyncMock(return_value="tree-sha"),
        "create_commit": AsyncMock(return_value="commit-sha"),
        "create_ref": AsyncMock(),
        "update_ref": AsyncMock(),
        "create_pull_request": AsyncMock(return_value={"html_url": "https://github.com/acme/widgets/pull/7", "number": 7}),
    }
    return mocks


def _patches(client_mocks, perms_resp):
    gc_patches = [
        patch.object(coder_router.GitHubClient, name, mock) for name, mock in client_mocks.items()
    ]
    # The router calls github_client._request (module attribute lookup), so
    # patching it here intercepts the permission probe inside _execute_export_job.
    req_patch = patch(
        "open_webui.utils.coder.github_client._request",
        AsyncMock(return_value=perms_resp),
    )
    return gc_patches + [req_patch]


class ClientCtx:
    """Patch only GitHubClient static methods (the real _request stays intact —
    export_worker._run_export wraps calls in try/except GitHubAPIError)."""

    def __init__(self, client_mocks):
        self._patches = [
            patch.object(coder_router.GitHubClient, name, mock) for name, mock in client_mocks.items()
        ]

    def __enter__(self):
        for p in self._patches:
            p.start()
        return self

    def __exit__(self, *exc_info):
        for p in reversed(self._patches):
            p.stop()
        return False


class PatchesCtx:
    def __init__(self, patches):
        self._patches = list(patches)

    def __enter__(self):
        for p in self._patches:
            p.start()
        return self

    def __exit__(self, *exc_info):
        for p in reversed(self._patches):
            p.stop()
        return False


def test_execute_export_job_symbol_exists():
    """The worker imports this by name — it must be defined on the router module."""
    assert callable(getattr(coder_router, "_execute_export_job", None))


def test_execute_export_job_full_sequence():
    perms = _resp(200, {"permissions": {"push": True}})
    mocks = _client_mocks(branch_exists=False)
    with PatchesCtx(_patches(mocks, perms)):
        sha, pr_url, pr_number = run(coder_router._execute_export_job("job-1", "tok", dict(FORM)))
    assert (sha, pr_url, pr_number) == ("commit-sha", "https://github.com/acme/widgets/pull/7", 7)
    mocks["create_blob"].assert_awaited_once()
    mocks["create_ref"].assert_awaited_once()
    mocks["update_ref"].assert_not_awaited()


def test_execute_export_job_existing_branch_updates_ref():
    perms = _resp(200, {"permissions": {"push": True}})
    mocks = _client_mocks(branch_exists=True)
    with PatchesCtx(_patches(mocks, perms)):
        run(coder_router._execute_export_job("job-2", "tok", dict(FORM)))
    mocks["update_ref"].assert_awaited_once()
    mocks["create_ref"].assert_not_awaited()


def test_execute_export_job_forbidden_without_push():
    from fastapi import HTTPException

    perms = _resp(200, {"permissions": {"push": False}})
    mocks = _client_mocks(branch_exists=False)
    with PatchesCtx(_patches(mocks, perms)):
        try:
            run(coder_router._execute_export_job("job-3", "tok", dict(FORM)))
            assert False, "expected HTTPException"
        except HTTPException as exc:
            assert exc.status_code == 403
            assert exc.detail["code"] == "CODER_FORBIDDEN"


def test_execute_export_job_repo_not_found():
    from fastapi import HTTPException

    perms = _resp(404)
    mocks = _client_mocks(branch_exists=False)
    # GitHubClient must stay mocked: if the patch of the permission probe ever
    # stops intercepting, the real client would hit api.github.com over network.
    with PatchesCtx(_patches(mocks, perms)):
        try:
            run(coder_router._execute_export_job("job-4", "tok", dict(FORM)))
            assert False, "expected HTTPException"
        except HTTPException as exc:
            assert exc.status_code == 404
            assert exc.detail["code"] == "CODER_NOT_FOUND"
    mocks["get_ref_commit_sha"].assert_not_awaited()


def test_worker_run_export_persists_completed_status():
    """Regression: schedule_export/_run_export must resolve _execute_export_job
    (previously ImportError -> every async job failed) and persist completion."""
    perms = _resp(200, {"permissions": {"push": True}})
    mocks = _client_mocks(branch_exists=False)

    updates = []

    async def fake_update(job_id, data, db):
        updates.append(data)

    db = MagicMock()
    db.commit = AsyncMock()
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=db)
    ctx.__aexit__ = AsyncMock(return_value=False)

    # Patch the router's `github_request` alias AND the module-level `_request`
    # (the permission probe resolves it via github_client module attribute).
    req_patch = patch.object(coder_router, "github_request", AsyncMock(return_value=perms))
    gh_req_patch = patch(
        "open_webui.utils.coder.github_client._request",
        AsyncMock(return_value=perms),
    )
    with req_patch, gh_req_patch, \
         ClientCtx(mocks), \
         patch.object(export_worker, "get_async_db", lambda: ctx), \
         patch.object(coder_router.CoderExportJobs, "update", fake_update), \
         patch.object(export_worker.CoderAudit, "record", AsyncMock()), \
         patch.object(export_worker, "observe_export_job", MagicMock()):
        run(export_worker._run_export("job-5", "user-1", "tok", dict(FORM), None))

    statuses = [u.get("status") for u in updates]
    assert statuses == ["running", "completed"], statuses
    assert updates[-1]["pr_url"] == "https://github.com/acme/widgets/pull/7"
