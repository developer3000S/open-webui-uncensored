"""§D: подключение репозиториев и аккаунтов — org filter, валидация соединения.

Тесты (mock GitHub API, без сети):
 - GET /repos?org=... : чужая организация -> 403 (CODER_ORG_NOT_ALLOWED), запрос
   к списку репозиториев не выполняется; своя организация проходит дальше;
   без org дополнительный round-trip к /user/orgs не делается;
 - GET /github/organizations отдаёт логин+аватар организаций;
 - POST /github/validate: scopes с "repo" -> valid без warning; только
   "public_repo" -> предупреждение; ошибка GitHub API -> HTTPException с кодом;
 - GET /github/connection_status: список подключений без обращения к сети.
"""

import asyncio
import os
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

os.environ.setdefault("WEBUI_SECRET_KEY", "test")

from fastapi import HTTPException  # noqa: E402


def run(coro):
    return asyncio.run(coro)


def _request_stub(user_id="u1"):
    req = MagicMock()
    req.app.state = MagicMock()
    req.state = MagicMock()
    req.headers = {}
    req.url = MagicMock()
    req.base_url = "http://test"
    return req


class _PatchList:
    """Контекст-менеджер для набора патчей (starred tuple unpacking требует Python 3.13+)."""

    def __init__(self, patches):
        self._patches = list(patches)

    def __enter__(self):
        for p in self._patches:
            p.__enter__()
        return self

    def __exit__(self, *exc_info):
        for p in reversed(self._patches):
            p.__exit__(*exc_info)
        return False


def _repos_patches(list_repos_mock):
    from open_webui.routers import coder as coder_router

    return [
        patch.object(coder_router, "check_coder_permission", new=AsyncMock()),
        patch.object(coder_router, "_get_connection_host", new=AsyncMock(return_value="github.com")),
        patch.object(coder_router, "_get_connection_token", new=AsyncMock(return_value="tok")),
        patch.object(coder_router.GitHubClient, "list_repositories", new=list_repos_mock),
        patch.object(
            coder_router,
            "get_coder_policies",
            new=AsyncMock(return_value={"allowed_github_hosts": [], "allowed_orgs": [], "allowed_repos": [], "blocked_paths": []}),
        ),
    ]


def test_endpoint_repos_org_membership_denied():
    """Чужая организация -> 403, список репозиториев GitHub не запрашивается."""
    from open_webui.routers import coder as coder_router

    list_repos = AsyncMock()
    orgs_resp = MagicMock()
    orgs_resp.status_code = 200
    orgs_resp.json.return_value = [{"login": "acme"}, {"login": "widgets"}]
    patches = _repos_patches(list_repos) + [patch.object(coder_router, "github_request", new=AsyncMock(return_value=orgs_resp))]
    with _PatchList(patches):
        with pytest.raises(HTTPException) as exc:
            run(
                coder_router.coder_repos(
                    _request_stub(), query=None, page=1, org="evil-corp", connection_id=None,
                    user=SimpleNamespace(id="u1", role="user"), db=AsyncMock(),
                )
            )
    assert exc.value.status_code == 403
    assert exc.value.detail["code"] == "CODER_ORG_NOT_ALLOWED"
    list_repos.assert_not_awaited()


def test_endpoint_repos_org_allowed_passes_filter():
    """Своя организация пропускается и уходит в GitHubClient.list_repositories(org=...)."""
    from open_webui.routers import coder as coder_router

    repos = [{"owner": "acme", "name": "app", "full_name": "acme/app", "default_branch": "main", "private": False}]
    list_repos = AsyncMock(return_value=repos)
    orgs_resp = MagicMock()
    orgs_resp.status_code = 200
    orgs_resp.json.return_value = [{"login": "acme"}]
    patches = _repos_patches(list_repos) + [patch.object(coder_router, "github_request", new=AsyncMock(return_value=orgs_resp))]
    with _PatchList(patches):
        result = run(
            coder_router.coder_repos(
                _request_stub(), query=None, page=1, org="acme", connection_id=None,
                user=SimpleNamespace(id="u1", role="user"), db=AsyncMock(),
            )
        )
    assert result["repos"] == repos
    kwargs = list_repos.await_args.kwargs
    assert kwargs.get("org") == "acme"


def test_endpoint_repos_without_org_skips_membership_check():
    from open_webui.routers import coder as coder_router

    list_repos = AsyncMock(return_value=[])
    github_request = AsyncMock()
    patches = _repos_patches(list_repos) + [patch.object(coder_router, "github_request", new=github_request)]
    with _PatchList(patches):
        result = run(
            coder_router.coder_repos(
                _request_stub(), query=None, page=1, org=None, connection_id=None,
                user=SimpleNamespace(id="u1", role="user"), db=AsyncMock(),
            )
        )
    assert result == {"repos": []}
    github_request.assert_not_awaited()  # no extra /user/orgs round-trip


def test_endpoint_github_organizations_lists_logins():
    from open_webui.routers import coder as coder_router

    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = [{"login": "acme", "avatar_url": "a.png"}, {"login": "widgets"}]
    with (
        patch.object(coder_router, "check_coder_permission", new=AsyncMock()),
        patch.object(coder_router, "_get_connection_token", new=AsyncMock(return_value="tok")),
        patch.object(coder_router, "_get_connection_host", new=AsyncMock(return_value="github.com")),
        patch.object(coder_router, "github_request", new=AsyncMock(return_value=resp)),
        patch.object(coder_router, "_audit", new=AsyncMock()),
    ):
        result = run(
            coder_router.github_organizations(
                _request_stub(), connection_id=None, user=SimpleNamespace(id="u1", role="user"), db=AsyncMock()
            )
        )
    assert result["organizations"] == [
        {"login": "acme", "avatar_url": "a.png"},
        {"login": "widgets", "avatar_url": None},
    ]


def test_endpoint_github_validate_ok_and_scope_warning():
    from open_webui.routers import coder as coder_router

    conn = MagicMock()
    conn.scopes = ["public_repo"]
    conn.token_type = "oauth"
    patches_common = [
        patch.object(coder_router, "check_coder_permission", new=AsyncMock()),
        patch.object(coder_router, "_get_connection_token", new=AsyncMock(return_value="tok")),
        patch.object(coder_router, "_get_connection_host", new=AsyncMock(return_value="github.com")),
        patch.object(coder_router, "_get_connection", new=AsyncMock(return_value=conn)),
        patch.object(coder_router, "_audit", new=AsyncMock()),
    ]
    with _PatchList(
        patches_common + [
            patch.object(coder_router.GitHubClient, "get_user", new=AsyncMock(return_value={"login": "octo"}))
        ]
    ):
        result = run(
            coder_router.github_validate(
                _request_stub(), connection_id=None, user=SimpleNamespace(id="u1", role="user"), db=AsyncMock()
            )
        )
    assert result["valid"] is True
    assert result["login"] == "octo"
    assert result["has_repo_scope"] is False
    assert result["warning"]  # public_repo-only token -> UI warning about private repos

    conn.scopes = ["repo"]
    with _PatchList(
        patches_common + [
            patch.object(coder_router.GitHubClient, "get_user", new=AsyncMock(return_value={"login": "octo"}))
        ]
    ):
        result = run(
            coder_router.github_validate(
                _request_stub(), connection_id=None, user=SimpleNamespace(id="u1", role="user"), db=AsyncMock()
            )
        )
    assert result["has_repo_scope"] is True
    assert result["warning"] is None


def test_endpoint_github_validate_maps_api_error():
    from open_webui.routers import coder as coder_router
    from open_webui.utils.coder.github_client import GitHubAPIError

    conn = MagicMock()
    conn.scopes = ["repo"]
    conn.token_type = "oauth"
    with (
        patch.object(coder_router, "check_coder_permission", new=AsyncMock()),
        patch.object(coder_router, "_get_connection_token", new=AsyncMock(return_value="tok")),
        patch.object(coder_router, "_get_connection_host", new=AsyncMock(return_value="github.com")),
        patch.object(coder_router, "_get_connection", new=AsyncMock(return_value=conn)),
        patch.object(coder_router, "_audit", new=AsyncMock()),
        patch.object(
            coder_router.GitHubClient, "get_user",
            new=AsyncMock(side_effect=GitHubAPIError("CODER_GITHUB_BAD_TOKEN", "Bad credentials", 401)),
        ),
    ):
        with pytest.raises(HTTPException) as exc:
            run(
                coder_router.github_validate(
                    _request_stub(), connection_id=None, user=SimpleNamespace(id="u1", role="user"), db=AsyncMock()
                )
            )
    assert exc.value.status_code == 401
    assert exc.value.detail["code"] == "CODER_GITHUB_BAD_TOKEN"


def test_endpoint_connection_status_reports_connections_without_network():
    from open_webui.routers import coder as coder_router

    c1 = MagicMock()
    c1.id = "c1"
    c1.github_login = "octo"
    c1.github_host = "github.com"
    c1.token_type = "oauth"
    c1.is_default = True
    c1.scopes = ["repo"]
    c2 = MagicMock()
    c2.id = "c2"
    c2.github_login = "bot"
    c2.github_host = "ghe.corp"
    c2.token_type = "app_installation"
    c2.is_default = False
    c2.scopes = []
    with (
        patch.object(coder_router, "check_coder_permission", new=AsyncMock()),
        patch.object(coder_router.CoderGithubConnections, "list_by_user_id", new=AsyncMock(return_value=[c1, c2])),
    ):
        result = run(
            coder_router.github_connection_status(
                _request_stub(), connection_id=None, user=SimpleNamespace(id="u1", role="user"), db=AsyncMock()
            )
        )
    assert result["connected"] is True
    assert [c["id"] for c in result["connections"]] == ["c1", "c2"]
    assert result["connections"][0]["scopes_ok"] is True
    assert result["connections"][1]["scopes_ok"] is True  # app installation tokens always OK
