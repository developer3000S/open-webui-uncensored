"""Coder section router.

Endpoints (per technical specification Coder.md):
- GET  /config                        - feature status & GitHub OAuth availability
- GET  /github/auth/start             - begin GitHub OAuth web flow (CSRF state)
- GET  /github/auth/callback          - OAuth callback, stores encrypted token
- GET  /github/connection             - current connection info
- DELETE /github/connection           - disconnect GitHub account
- GET  /repos                         - list/search repositories
- GET  /branches                      - list branches of a repo
- GET  /tree                          - file tree for repo@branch
- GET  /file                          - single file content
- POST /changeset/validate            - validate change set + generate diffs
- POST /export/preview                - preview export (validation + diff summary)
- POST /export/start                  - start export job (commit to branch + mandatory PR)
- GET  /export/jobs                   - list export jobs
- GET  /export/jobs/{job_id}          - export job status
- GET  /audit                         - audit events for the user
"""

import logging
import re
from urllib.parse import quote
import secrets
import time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import PlainTextResponse, RedirectResponse
from open_webui.config import CODER_ENABLED, CODER_GITHUB_CLIENT_ID, CODER_AUDIT_RETENTION_DAYS, WEBUI_URL
from open_webui.constants import ERROR_MESSAGES
from open_webui.internal.db import get_async_session
from open_webui.models.coder import (
    CoderAudit,
    CoderExportForm,
    CoderGitHubAppConnectionForm,
    CoderGitHubAppInstallationForm,
    CoderGitHubAppInstallations,
    CoderGithubConnections,
    CoderProjectForm,
    CoderProjects,
    CoderExportJobs,
    CoderSandboxCreateForm,
    CoderSandboxSession,
    CoderSandboxSessionModel,
    CoderSandboxSessions,
    CoderTaskMetaForm,
    CoderTaskMetaModel,
    CoderTaskMetas,
)
from open_webui.models.config import Config
from open_webui.utils.auth import get_verified_user, get_admin_user
from open_webui.utils.coder import export_worker
from open_webui.utils.coder.changeset import ChangeSetValidationError, generate_unified_diff, validate_changeset, validate_path
from open_webui.utils.coder.crypto import decrypt_secret, encrypt_secret
from open_webui.utils.coder.github_client import (
    GitHubAPIError,
    GitHubClient,
    _api_base as _api_base_for,
    _request as github_request,
)
from open_webui.utils.coder.metrics import (
    CODER_ACTIVE_CONNECTIONS,
    CODER_REQUESTS_TOTAL,
    observe_audit_event,
    observe_stream,
    render_metrics,
)
from open_webui.utils.coder import modes as coder_modes
from open_webui.utils.coder import sandbox as coder_sandbox
from open_webui.utils.coder.sandbox import SandboxError
from open_webui.utils.coder.policy import get_coder_policies, host_is_allowed, owner_is_allowed, repo_is_allowed
from pydantic import BaseModel
from sqlalchemy import select as sa_select
from sqlalchemy.ext.asyncio import AsyncSession

log = logging.getLogger(__name__)

router = APIRouter()

OAUTH_STATE_TTL_SECONDS = 600
# in-memory CSRF state store: state -> {user_id, expires}
_oauth_states: dict[str, dict] = {}


class CoderChangeSetForm(BaseModel):
    files: list[dict[str, Any]]


class CoderReviewCommentForm(BaseModel):
    owner: str
    repo: str
    pr_number: str
    path: str
    line: int
    body: str
    side: str = 'RIGHT'


class CoderGistExportForm(BaseModel):
    description: str = ''
    public: bool = False
    files: dict[str, str]


class CoderTestIssueForm(BaseModel):
    owner: str
    repo: str
    title: str
    body: str = ''
    labels: list[str] = ['automated-tests']


async def check_coder_permission(request: Request, user):
    config = await Config.get_many('coder.enable')
    if not config.get('coder.enable', CODER_ENABLED):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=ERROR_MESSAGES.UNAUTHORIZED,
        )


def _client_ip(request: Request) -> str | None:
    # Учитываем прокси: первый ненулевой адрес из X-Forwarded-For
    forwarded = request.headers.get('x-forwarded-for')
    if forwarded:
        return forwarded.split(',')[0].strip() or None
    if request.client and request.client.host not in (None, '', 'testclient'):
        return request.client.host
    return None


def _user_agent(request: Request) -> str | None:
    ua = request.headers.get('user-agent')
    return ua.strip() if ua and ua.strip() else None


def _correlation_id(request: Request) -> str | None:
    # Заголовок запроса (traceparent/X-Correlation-ID) или span/otel контекст
    for header in ('x-correlation-id', 'x-request-id', 'traceparent'):
        value = request.headers.get(header)
        if value:
            return value.strip().split('-')[0] if header == 'traceparent' else value.strip()
    return None


async def _audit(
    request: Request,
    user_id: str,
    action: str,
    target: str | None = None,
    payload: dict | None = None,
    db: AsyncSession = None,
) -> None:
    """§14.1/§11.4: записать событие аудита с сетевым и корреляционным контекстом."""
    try:
        await CoderAudit.record(
            user_id=user_id,
            action=action,
            target=target,
            payload=payload,
            correlation_id=_correlation_id(request),
            ip_address=_client_ip(request),
            user_agent=_user_agent(request),
            db=db,
        )
        observe_audit_event(action)
    except Exception:
        log.debug('coder audit record failed', exc_info=True)


def _retry_settings_from_policies(policies: dict) -> dict:
    return {
        'max_retries': policies['retry_max'],
        'timeout': float(policies['timeout']),
        'policy': policies['retry_policy'],
        'base_delay': float(policies['retry_delay']),
    }


async def _check_repo_access(
    request: Request, policies: dict, owner: str, repo: str, user_id: str, db: AsyncSession, connection_host: str | None = None
) -> None:
    """§15.1 admin policies: hosts/orgs/repos allow-list enforcement (§14.1 permission_denied)."""
    target_host = connection_host or 'github.com'
    host_ok = host_is_allowed(target_host, policies['allowed_github_hosts'])
    if not (host_ok and owner_is_allowed(owner, policies['allowed_orgs']) and repo_is_allowed(f'{owner}/{repo}', policies['allowed_repos'])):
        await _audit(
            request,
            user_id=user_id,
            action='permission_denied',
            target=f'{owner}/{repo}',
            payload={'reason': 'repo_not_allowed'},
            db=db,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={'code': 'CODER_DISALLOWED_REPO', 'message': f'Repository "{owner}/{repo}" is not allowed by server policy'},
        )


async def _get_connection(user_id: str, db: AsyncSession, connection_id: str | None = None):
    """Resolve a GitHub connection (§22.2 multi-GitHub).

    When connection_id is given it must belong to the user; otherwise the
    user's default connection is used (back-compatible with single-account UI).
    """
    if connection_id:
        connection = await CoderGithubConnections.get_by_id(connection_id, user_id, db)
        if not connection:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={'code': 'CODER_CONNECTION_NOT_FOUND', 'message': 'GitHub connection not found'},
            )
    else:
        connection = await CoderGithubConnections.get_by_user_id(user_id, db)
    if not connection:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={'code': 'CODER_NOT_CONNECTED', 'message': 'GitHub account is not connected'},
        )
    return connection


async def _get_connection_token(user_id: str, db: AsyncSession, connection_id: str | None = None) -> str:
    connection = await _get_connection(user_id, db, connection_id)
    # Priority D: GitHub App installation — mint/refresh short-lived token on demand.
    if connection.token_type == 'app_installation' and connection.installation_id:
        from open_webui.utils.coder.github_client import get_installation_token

        try:
            return await get_installation_token(connection.installation_id, connection.github_host)
        except GitHubAPIError as exc:
            raise HTTPException(
                status_code=exc.status_code or status.HTTP_502_BAD_GATEWAY,
                detail={'code': exc.code, 'message': exc.message},
            )
    try:
        token = decrypt_secret(connection.access_token_encrypted)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={'code': 'CODER_DECRYPTION_FAILED', 'message': 'Failed to decrypt stored GitHub token'},
        )
    return token


async def _get_connection_host(user_id: str, db: AsyncSession, connection_id: str | None = None) -> str:
    connection = await _get_connection(user_id, db, connection_id)
    return connection.github_host or 'github.com'


def _prune_oauth_states():
    now = time.time()
    expired = [k for k, v in _oauth_states.items() if v['expires'] < now]
    for k in expired:
        _oauth_states.pop(k, None)


############################
# Config
############################


@router.get('/config')
async def get_coder_config(request: Request, user=Depends(get_verified_user), db: AsyncSession = Depends(get_async_session)):
    policies = await get_coder_policies()
    await _audit(request, user.id, action='section_accessed', target='config', db=db)
    return {
        'enabled': CODER_ENABLED,
        'github_oauth_configured': bool(CODER_GITHUB_CLIENT_ID),
        'github_client_id': CODER_GITHUB_CLIENT_ID or None,
        'policies': {
            'allowed_github_hosts': policies['allowed_github_hosts'],
            'allowed_orgs': policies['allowed_orgs'],
            'allowed_repos': policies['allowed_repos'],
            'blocked_paths': policies['blocked_paths'],
            'require_pr': policies['require_pr'],
            'max_files_per_changeset': policies['max_files_per_changeset'],
            'max_total_diff_size': policies['max_total_diff_size'],
            'async_export': policies['async_export'],
        },
    }


@router.get('/admin/policies')
async def coder_admin_policies(user=Depends(get_admin_user)):
    """§15.1: полный обзор административных политик Coder (только admin)."""
    policies = await get_coder_policies()
    return policies


@router.get('/metrics')
async def coder_metrics(user=Depends(get_admin_user)):
    """§14.2: prometheus-метрики coder_* (только admin)."""
    return PlainTextResponse(content=render_metrics().decode('utf-8'), media_type='text/plain; version=0.0.4; charset=utf-8')


############################
# GitHub OAuth
############################


@router.get('/github/auth/start')
async def github_auth_start(request: Request, host: str | None = None, user=Depends(get_verified_user)):
    await check_coder_permission(request, user)
    if not CODER_GITHUB_CLIENT_ID:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={'code': 'CODER_OAUTH_NOT_CONFIGURED', 'message': 'GitHub OAuth is not configured on this server'},
        )
    # §22.2 multi-GitHub: connect an additional account or a GitHub Enterprise host
    gh_host = (host or 'github.com').strip().lower().removeprefix('https://').removeprefix('http://').rstrip('/')
    policies = await get_coder_policies()
    if not host_is_allowed(gh_host, policies['allowed_github_hosts']):
        await _audit(request, user.id, action='permission_denied', target=gh_host, payload={'reason': 'host_not_allowed'})
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={'code': 'CODER_DISALLOWED_HOST', 'message': f'GitHub host "{gh_host}" is not allowed by server policy'},
        )
    _prune_oauth_states()
    state = secrets.token_urlsafe(32)
    _oauth_states[state] = {'user_id': user.id, 'host': gh_host, 'expires': time.time() + OAUTH_STATE_TTL_SECONDS}

    redirect_uri = str(request.url_for('github_auth_callback'))
    # Default consent settings:
    # - scope `repo` grants Contents: Read & Write on all accessible repos,
    #   which is what "Repository access → All repositories" + "Contents: Read"
    #   requires; `public_repo` additionally keeps public repos readable if the
    #   user narrows access to "Only select repositories".
    # Note: GitHub's OAuth/OAuth-app consent screen does not accept URL
    # parameters that preselect repository access — the defaults above are the
    # closest achievable behaviour. The admin must also enable "All repositories"
    # under Third-party App access in the GitHub App / OAuth App settings for
    # org members (see docs/CODER.md §6).
    authorize_url = (
        f'https://{gh_host}/login/oauth/authorize'
        f'?client_id={CODER_GITHUB_CLIENT_ID}'
        f'&redirect_uri={redirect_uri}'
        f'&scope={" ".join(["repo", "public_repo"])}'
        f'&state={state}'
    )
    return {'url': authorize_url}


def _coder_redirect_url(request: Request, query: str) -> str:
    """Build an absolute redirect URL back to the /coder page.

    A relative location ('/coder?...') breaks behind reverse proxies or when
    the app is served under a path prefix — GitHub's OAuth flow requires an
    absolute URL and browsers drop the query when the redirect target loses
    the origin. Prefer WEBUI_URL, then standard proxy forwarding headers,
    then the request URL itself.
    """
    base = (WEBUI_URL or '').strip().rstrip('/')
    if not base:
        forwarded_proto = request.headers.get('x-forwarded-proto', '').split(',')[0].strip()
        forwarded_host = request.headers.get('x-forwarded-host', '').split(',')[0].strip()
        if forwarded_host:
            scheme = forwarded_proto or request.url.scheme
            base = f'{scheme}://{forwarded_host}'
            root_path = (getattr(request.app.state, 'ROOT_PATH', '') or '').strip('/')
            if root_path:
                base = f'{base}/{root_path}'
        else:
            base = str(request.base_url).rstrip('/')
    # standalone=1 — Coder opens as a separate application window
    return f'{base}/coder?standalone=1&{query}'


@router.get('/github/auth/callback')
async def github_auth_callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    db: AsyncSession = Depends(get_async_session),
):
    if error or not code or not state:
        return RedirectResponse(url=_coder_redirect_url(request, 'github_error=denied'), status_code=302)

    _prune_oauth_states()
    state_data = _oauth_states.pop(state, None)
    if not state_data:
        return RedirectResponse(url=_coder_redirect_url(request, 'github_error=invalid_state'), status_code=302)
    user_id = state_data['user_id']
    gh_host = state_data.get('host', 'github.com')

    try:
        token_data = await GitHubClient.exchange_code(code, host=gh_host)
        gh_user = await GitHubClient.get_user(token_data['access_token'], host=gh_host)
    except GitHubAPIError as exc:
        log.exception('Coder GitHub OAuth callback failed')
        return RedirectResponse(url=_coder_redirect_url(request, 'github_error=api_failure'), status_code=302)

    granted_scopes = [s.strip() for s in (token_data.get('scope') or '').split(',') if s.strip()]
    if 'repo' not in granted_scopes:
        # Token was issued without repository access — send the user through the
        # consent screen again so GitHub prompts to approve the `repo` scope.
        return RedirectResponse(url=_coder_redirect_url(request, 'github_retry_auth=1'), status_code=302)

    # Verify the stored token can actually access repository data (/user/repos);
    # otherwise surface a clear error instead of silently showing an empty list.
    try:
        await GitHubClient.list_repositories(token_data['access_token'], page=1, per_page=1, host=gh_host)
    except GitHubAPIError as exc:
        log.warning(f'Coder GitHub token validation failed for {gh_host}:{gh_user["login"]}: {exc.code} {exc.message}')
        return RedirectResponse(url=_coder_redirect_url(request, 'github_error=insufficient_scopes'), status_code=302)

    encrypted = encrypt_secret(token_data['access_token'])
    await CoderGithubConnections.upsert(
        user_id=user_id,
        github_login=gh_user['login'],
        github_user_id=gh_user['id'],
        access_token_encrypted=encrypted,
        scopes=granted_scopes,
        github_host=gh_host,
        db=db,
    )
    await _audit(request, user_id, action='github_connect', target=f"{gh_host}:{gh_user['login']}", db=db)
    await db.commit()
    return RedirectResponse(url=_coder_redirect_url(request, 'github_connected=1'), status_code=302)


@router.get('/github/connection')
async def github_connection(request: Request, user=Depends(get_verified_user), db: AsyncSession = Depends(get_async_session)):
    await check_coder_permission(request, user)
    connection = await CoderGithubConnections.get_by_user_id(user.id, db)
    if not connection:
        try:
            from open_webui.internal.db import AsyncSessionLocal
            from sqlalchemy import func, select
            from open_webui.models.coder import CoderGithubConnection

            async with AsyncSessionLocal() as cnt_db:
                total = (await cnt_db.execute(select(func.count()).select_from(CoderGithubConnection))).scalar() or 0
            CODER_ACTIVE_CONNECTIONS.set(total)
        except Exception:
            log.debug('coder connections gauge failed', exc_info=True)
        return {'connected': False}
    return {
        'connected': True,
        'github_login': connection.github_login,
        'scopes': connection.scopes,
        'updated_at': connection.updated_at,
    }


@router.delete('/github/connection')
async def github_disconnect(request: Request, user=Depends(get_verified_user), db: AsyncSession = Depends(get_async_session)):
    await check_coder_permission(request, user)
    await CoderGithubConnections.delete_by_user_id(user.id, db)
    await _audit(request, user.id, action='github_disconnect', db=db)
    return {'status': True}


@router.get('/github/connections')
async def github_connections_list(request: Request, user=Depends(get_verified_user), db: AsyncSession = Depends(get_async_session)):
    """§22.2 multi-GitHub: все подключения пользователя (без токенов)."""
    await check_coder_permission(request, user)
    connections = await CoderGithubConnections.list_by_user_id(user.id, db)
    return {
        'connections': [
            {
                'id': c.id,
                'github_login': c.github_login,
                'github_host': c.github_host or 'github.com',
                'scopes': c.scopes,
                'is_default': bool(c.is_default),
                'updated_at': c.updated_at,
            }
            for c in connections
        ]
    }


@router.post('/github/connections/{connection_id}/default')
async def github_connection_set_default(
    request: Request, connection_id: str, user=Depends(get_verified_user), db: AsyncSession = Depends(get_async_session)
):
    """Назначить подключение по умолчанию для всех операций Coder."""
    await check_coder_permission(request, user)
    ok = await CoderGithubConnections.set_default(connection_id, user.id, db)
    if not ok:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=ERROR_MESSAGES.NOT_FOUND)
    await db.commit()
    await _audit(request, user.id, action='github_connection_default_changed', target=connection_id, db=db)
    return {'status': True}


@router.delete('/github/connections/{connection_id}')
async def github_connection_delete(
    request: Request, connection_id: str, user=Depends(get_verified_user), db: AsyncSession = Depends(get_async_session)
):
    """Отключить одно GitHub-подключение (остальные сохраняются)."""
    await check_coder_permission(request, user)
    ok = await CoderGithubConnections.delete_by_id(connection_id, user.id, db)
    if not ok:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=ERROR_MESSAGES.NOT_FOUND)
    await db.commit()
    await _audit(request, user.id, action='github_connection_deleted', target=connection_id, db=db)
    return {'status': True}


############################
# GitHub App & connection validation (plan coder.qwen.ai, priority D)
############################


@router.get('/github-app/status')
async def github_app_status(
    request: Request, user=Depends(get_verified_user), db: AsyncSession = Depends(get_async_session)
):
    """Настроено ли GitHub App и какие установки видны пользователю."""
    from open_webui.utils.coder.github_client import (
        github_app_configured,
        github_app_install_url,
        list_user_installations,
    )

    await check_coder_permission(request, user)
    configured = github_app_configured()
    install_url = github_app_install_url() if configured else None
    installations = await CoderGitHubAppInstallations.list_by_user_id(user.id, db)
    # live sync with GitHub when an OAuth token exists and the app is configured
    live: list[dict] = []
    if configured:
        try:
            oauth_conn = await CoderGithubConnections.get_by_user_id(user.id, db)
            if oauth_conn and oauth_conn.token_type != 'app_installation':
                token = decrypt_secret(oauth_conn.access_token_encrypted)
                live = await list_user_installations(token, oauth_conn.github_host)
                for item in live:
                    await CoderGitHubAppInstallations.upsert(
                        user.id, CoderGitHubAppInstallationForm(**item), db
                    )
                await db.commit()
                installations = await CoderGitHubAppInstallations.list_by_user_id(user.id, db)
        except Exception as exc:  # non-fatal: cached rows remain usable
            log.debug(f'github-app live sync failed: {exc}')
    return {
        'configured': configured,
        'install_url': install_url,
        'installations': [
            {
                'installation_id': i.installation_id,
                'account_login': i.account_login,
                'account_type': i.account_type,
                'repository_selection': i.repository_selection,
                'github_host': i.github_host,
            }
            for i in installations
        ],
    }


@router.post('/github-app/connection')
async def github_app_connect(
    request: Request,
    form: CoderGitHubAppConnectionForm,
    user=Depends(get_verified_user),
    db: AsyncSession = Depends(get_async_session),
):
    """Сделать GitHub App installation активным подключением пользователя."""
    from open_webui.utils.coder.github_client import get_installation_token

    await check_coder_permission(request, user)
    policies = await get_coder_policies()
    host = form.github_host or 'github.com'
    if policies['allowed_github_hosts'] and host not in policies['allowed_github_hosts']:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={'code': 'CODER_DISALLOWED_HOST', 'message': f'Host "{host}" is not allowed by server policy'},
        )
    row = await CoderGitHubAppInstallations.get_by_installation(user.id, form.installation_id, db)
    if not row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={'code': 'CODER_INSTALLATION_NOT_FOUND', 'message': 'Unknown installation; refresh /github-app/status first'},
        )
    # verify the installation actually works before switching the connection over
    try:
        token = await get_installation_token(form.installation_id, host)
        me = await GitHubClient.get_user(token, host)
    except GitHubAPIError as exc:
        raise HTTPException(
            status_code=exc.status_code or status.HTTP_502_BAD_GATEWAY,
            detail={'code': exc.code, 'message': exc.message},
        )
    encrypted = encrypt_secret(f'app:{token[:8]}')  # placeholder secret; real token minted on demand
    connection = await CoderGithubConnections.upsert(
        user.id,
        github_login=row.account_login or me.get('login'),
        github_user_id=me.get('id'),
        access_token_encrypted=encrypted,
        scopes=['contents:read', 'contents:write'],
        github_host=host,
        token_type='app_installation',
        installation_id=form.installation_id,
        db=db,
    )
    await db.commit()
    await _audit(request, user.id, action='github_app_connected', target=f'{row.account_login}:{form.installation_id}', db=db)
    return {
        'connected': True,
        'connection_id': connection.id,
        'github_login': connection.github_login,
        'token_type': 'app_installation',
    }


@router.get('/github/organizations')
async def github_organizations(
    request: Request,
    connection_id: str | None = None,
    user=Depends(get_verified_user),
    db: AsyncSession = Depends(get_async_session),
):
    """Организации пользователя (для фильтра списка репозиториев)."""
    await check_coder_permission(request, user)
    token = await _get_connection_token(user.id, db, connection_id)
    host = await _get_connection_host(user.id, db, connection_id)
    api_base = _api_base_for(host)
    try:
        response = await github_request('GET', f'{api_base}/user/orgs', token=token, params={'per_page': 100})
        if response.status_code >= 400:
            raise GitHubAPIError('CODER_GITHUB_ERROR', f'orgs lookup failed ({response.status_code})', response.status_code)
        orgs = [{'login': o.get('login'), 'avatar_url': o.get('avatar_url')} for o in response.json()]
    except GitHubAPIError as exc:
        raise HTTPException(status_code=exc.status_code or 502, detail={'code': exc.code, 'message': exc.message})
    await _audit(request, user.id, action='github_orgs_viewed', db=db)
    return {'organizations': orgs}


@router.get('/github/connection_status')
async def github_connection_status(
    request: Request,
    connection_id: str | None = None,
    user=Depends(get_verified_user),
    db: AsyncSession = Depends(get_async_session),
):
    """Статус подключения без обращения к GitHub (быстрый UI-чек)."""
    await check_coder_permission(request, user)
    connections = await CoderGithubConnections.list_by_user_id(user.id, db)
    return {
        'connected': bool(connections),
        'connections': [
            {
                'id': c.id,
                'login': c.github_login,
                'host': c.github_host or 'github.com',
                'token_type': c.token_type,
                'is_default': bool(c.is_default),
                'scopes_ok': bool(c.scopes) and any(s in ('repo', 'public_repo', 'contents:read', 'contents:write') for s in c.scopes)
                if c.token_type == 'oauth'
                else True,
            }
            for c in connections
        ],
    }


@router.post('/github/validate')
async def github_validate(
    request: Request,
    connection_id: str | None = None,
    user=Depends(get_verified_user),
    db: AsyncSession = Depends(get_async_session),
):
    """Проверить валидность токена/scopes на GitHub (§D connection check)."""
    await check_coder_permission(request, user)
    token = await _get_connection_token(user.id, db, connection_id)
    host = await _get_connection_host(user.id, db, connection_id)
    conn = await _get_connection(user.id, db, connection_id)
    try:
        me = await GitHubClient.get_user(token, host)
    except GitHubAPIError as exc:
        await _audit(request, user.id, action='permission_denied', target='github_validate', db=db)
        raise HTTPException(
            status_code=exc.status_code or 502,
            detail={'code': exc.code, 'message': exc.message},
        )
    scopes = conn.scopes or []
    has_repo = conn.token_type == 'app_installation' or any(s in ('repo', 'public_repo') for s in scopes)
    return {
        'valid': True,
        'login': me.get('login'),
        'token_type': conn.token_type,
        'has_repo_scope': has_repo,
        'warning': None if has_repo else 'Token lacks the "repo" scope — private repositories will not be listed. Reconnect with updated scopes.',
    }


############################
# Repositories / branches / tree / file
############################


@router.get('/repos')
async def coder_repos(
    request: Request,
    query: str | None = None,
    page: int = 1,
    connection_id: str | None = None,
    user=Depends(get_verified_user),
    db: AsyncSession = Depends(get_async_session),
):
    await check_coder_permission(request, user)
    policies = await get_coder_policies()
    host = await _get_connection_host(user.id, db, connection_id)
    token = await _get_connection_token(user.id, db, connection_id)
    try:
        repos = await GitHubClient.list_repositories(token, query=query, page=page, host=host)
    except GitHubAPIError as exc:
        raise HTTPException(status_code=exc.status_code or status.HTTP_502_BAD_GATEWAY, detail={'code': exc.code, 'message': exc.message})
    # §15.1: показываем только разрешённые политики orgs/repos
    repos = [r for r in repos if owner_is_allowed(r.get('owner') or r.get('namespace', {}).get('login', ''), policies['allowed_orgs']) and repo_is_allowed(r.get('full_name', ''), policies['allowed_repos'])]
    return {'repos': repos}


@router.get('/branches')
async def coder_branches(
    request: Request,
    owner: str,
    repo: str,
    connection_id: str | None = None,
    user=Depends(get_verified_user),
    db: AsyncSession = Depends(get_async_session),
):
    await check_coder_permission(request, user)
    policies = await get_coder_policies()
    host = await _get_connection_host(user.id, db, connection_id)
    await _check_repo_access(request, policies, owner, repo, user.id, db, host)
    token = await _get_connection_token(user.id, db, connection_id)
    try:
        branches = await GitHubClient.list_branches(token, owner, repo, host=host)
    except GitHubAPIError as exc:
        raise HTTPException(status_code=exc.status_code or status.HTTP_502_BAD_GATEWAY, detail={'code': exc.code, 'message': exc.message})
    return {'branches': branches}


@router.get('/tree')
async def coder_tree(
    request: Request,
    owner: str,
    repo: str,
    branch: str,
    connection_id: str | None = None,
    user=Depends(get_verified_user),
    db: AsyncSession = Depends(get_async_session),
):
    await check_coder_permission(request, user)
    policies = await get_coder_policies()
    host = await _get_connection_host(user.id, db, connection_id)
    await _check_repo_access(request, policies, owner, repo, user.id, db, host)
    token = await _get_connection_token(user.id, db, connection_id)
    await _audit(request, user.id, action='repo_selected', target=f'{owner}/{repo}', payload={'branch': branch}, db=db)
    try:
        tree = await GitHubClient.get_tree(token, owner, repo, branch, host=host)
        project = await CoderProjects.get_by_user_repo(user.id, owner, repo, db)
        if not project:
            from open_webui.models.coder import CoderProjectForm

            project = await CoderProjects.upsert(user.id, CoderProjectForm(owner=owner, repo=repo, default_branch=branch), db)
    except GitHubAPIError as exc:
        raise HTTPException(status_code=exc.status_code or status.HTTP_502_BAD_GATEWAY, detail={'code': exc.code, 'message': exc.message})
    return {'tree': tree, 'project_id': project.id if project else None}


@router.get('/file')
async def coder_file(
    request: Request,
    owner: str,
    repo: str,
    path: str,
    branch: str,
    connection_id: str | None = None,
    user=Depends(get_verified_user),
    db: AsyncSession = Depends(get_async_session),
):
    await check_coder_permission(request, user)
    policies = await get_coder_policies()
    host = await _get_connection_host(user.id, db, connection_id)
    await _check_repo_access(request, policies, owner, repo, user.id, db, host)
    try:
        safe_path = validate_path(path, policies['blocked_paths'])
    except ChangeSetValidationError as exc:
        await _audit(request, user.id, action='permission_denied', target=path, payload={'reason': exc.code}, db=db)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail={'code': exc.code, 'message': exc.message})
    token = await _get_connection_token(user.id, db, connection_id)
    try:
        file = await GitHubClient.get_file(token, owner, repo, safe_path, branch, host=host)
    except GitHubAPIError as exc:
        if exc.code == 'CODER_GITHUB_RATE_LIMIT':
            await _audit(request, user.id, action='rate_limited', target=f'{owner}/{repo}:{safe_path}', db=db)
        raise HTTPException(status_code=exc.status_code or status.HTTP_502_BAD_GATEWAY, detail={'code': exc.code, 'message': exc.message})
    await _audit(request, user.id, action='file_viewed', target=f'{owner}/{repo}:{safe_path}', payload={'branch': branch}, db=db)
    return file


@router.post('/files/batch')
async def coder_files_batch(
    request: Request,
    form: dict,
    user=Depends(get_verified_user),
    db: AsyncSession = Depends(get_async_session),
):
    """Fetch several repository files in one call (used to preload repo context for coding)."""
    await check_coder_permission(request, user)
    owner = form.get('owner', '')
    repo = form.get('repo', '')
    branch = form.get('branch', '')
    paths = form.get('paths', [])[:30]
    if not (owner and repo and branch):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail={'code': 'invalid_request', 'message': 'owner, repo and branch are required'})
    policies = await get_coder_policies()
    connection_id = form.get('connection_id')
    host = await _get_connection_host(user.id, db, connection_id)
    await _check_repo_access(request, policies, owner, repo, user.id, db, host)
    token = await _get_connection_token(user.id, db, connection_id)
    files = []
    errors = []
    for p in paths:
        try:
            safe_path = validate_path(str(p), policies['blocked_paths'])
            file = await GitHubClient.get_file(token, owner, repo, safe_path, branch, host=host)
            if not file.get('binary'):
                files.append({'path': safe_path, 'content': file.get('content', '')})
        except ChangeSetValidationError as exc:
            errors.append({'path': str(p), 'message': exc.message})
        except GitHubAPIError as exc:
            errors.append({'path': str(p), 'message': exc.message})
        except Exception as exc:  # noqa: BLE001
            errors.append({'path': str(p), 'message': str(exc)})
    return {'files': files, 'errors': errors}


@router.get('/search')
async def coder_search(
    request: Request,
    owner: str,
    repo: str,
    branch: str,
    q: str,
    paths: str = '',
    max_results: int = 15,
    connection_id: str | None = None,
    user=Depends(get_verified_user),
    db: AsyncSession = Depends(get_async_session),
):
    """Agent-style repository search (like Qwen Coder / OpenAI Codex / opencode grep tools).

    Searches text content of the given files (or the whole repo tree when no paths
    are provided) for a literal or regex query and returns matching line snippets.
    """
    await check_coder_permission(request, user)
    if not (owner and repo and branch):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail={'code': 'invalid_request', 'message': 'owner, repo and branch are required'})
    try:
        pattern = re.compile(q if len(q) <= 200 else q[:200], re.IGNORECASE)
    except re.error:
        pattern = re.compile(re.escape(q[:200]), re.IGNORECASE)

    wanted = [p.strip() for p in paths.split(',') if p.strip()]
    policies = await get_coder_policies()
    host = await _get_connection_host(user.id, db, connection_id)
    await _check_repo_access(request, policies, owner, repo, user.id, db, host)
    token = await _get_connection_token(user.id, db, connection_id)

    CODE_EXT = re.compile(r'\.(ts|tsx|js|jsx|mjs|cjs|py|go|rs|java|kt|scala|c|h|cpp|hpp|cs|rb|php|swift|lua|vue|svelte|sql|sh|bash|zsh|yaml|yml|json|toml|ini|cfg|md|txt|html|css|scss|less|xml|gradle|make|dockerfile)$', re.IGNORECASE)
    SKIP_DIR = re.compile(r'(^|/)(node_modules|\.git|dist|build|out|vendor|venv|__pycache__|\.next|coverage|target)/', re.IGNORECASE)

    try:
        tree_entries = await GitHubClient.get_tree(token, owner, repo, branch, host=host)
        candidates = [e['path'] for e in tree_entries if e.get('type') == 'blob' and not SKIP_DIR.search(e['path']) and CODE_EXT.search(e['path'])]
        if wanted:
            wset = set(wanted)
            scoped = [p for p in candidates if p in wset]
            if not scoped:
                # fall back to raw requested paths even if extension filter excluded them
                scoped = [p for p in wanted if not SKIP_DIR.search(p)]
            candidates = scoped
        candidates = candidates[:600]
    except GitHubAPIError as exc:
        raise HTTPException(status_code=exc.status_code or status.HTTP_502_BAD_GATEWAY, detail={'code': exc.code, 'message': exc.message})

    matches = []
    errors = []
    fetched = 0
    for path in candidates:
        if len(matches) >= max(1, min(max_results, 50)):
            break
        try:
            safe_path = validate_path(path, policies['blocked_paths'])
            file = await GitHubClient.get_file(token, owner, repo, safe_path, branch, host=host)
            fetched += 1
            if file.get('binary'):
                continue
            lines = (file.get('content') or '').split('\n')
            hit_lines = []
            for i, line in enumerate(lines):
                if pattern.search(line):
                    start = max(0, i - 2)
                    end = min(len(lines), i + 3)
                    snippet = '\n'.join(f'{j+1}: {lines[j]}' for j in range(start, end))
                    hit_lines.append({'line': i + 1, 'snippet': snippet[:1200]})
                    if len(hit_lines) >= 3:
                        break
            if hit_lines:
                matches.append({'path': safe_path, 'hits': hit_lines})
        except ChangeSetValidationError as exc:
            errors.append({'path': path, 'message': exc.message})
        except GitHubAPIError as exc:
            errors.append({'path': path, 'message': exc.message})
        except Exception as exc:  # noqa: BLE001
            errors.append({'path': path, 'message': str(exc)})
    return {'query': q, 'scanned_files': fetched, 'considered_files': len(candidates), 'matches': matches, 'errors': errors}


@router.get('/search/semantic')
async def coder_semantic_search(
    request: Request,
    owner: str,
    repo: str,
    branch: str,
    q: str,
    max_results: int = 15,
    connection_id: str | None = None,
    user=Depends(get_verified_user),
    db: AsyncSession = Depends(get_async_session),
):
    """Semantic search по репозиторию (§22.2).

    Лексический префильтр + переупорядочивание эмбеддингами, если на сервере
    доступна embedding-модель; иначе — graceful fallback к лексическому рангу.
    """
    from open_webui.utils.coder import semantic

    await check_coder_permission(request, user)
    if not (owner and repo and branch and q):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail={'code': 'invalid_request', 'message': 'owner, repo, branch and q are required'})
    policies = await get_coder_policies()
    host = await _get_connection_host(user.id, db, connection_id)
    await _check_repo_access(request, policies, owner, repo, user.id, db, host)
    token = await _get_connection_token(user.id, db, connection_id)

    try:
        tree_entries = await GitHubClient.get_tree(token, owner, repo, branch, host=host)
    except GitHubAPIError as exc:
        raise HTTPException(status_code=exc.status_code or status.HTTP_502_BAD_GATEWAY, detail={'code': exc.code, 'message': exc.message})

    candidates = [e['path'] for e in tree_entries if e.get('type') == 'blob' and semantic.is_code_path(e['path'])]
    candidates = candidates[:semantic.MAX_CANDIDATES]

    files: dict[str, str] = {}
    errors = []
    for path in candidates:
        try:
            safe_path = validate_path(path, policies['blocked_paths'])
            file = await GitHubClient.get_file(token, owner, repo, safe_path, branch, host=host)
            if not file.get('binary'):
                files[safe_path] = file.get('content') or ''
        except ChangeSetValidationError as exc:
            errors.append({'path': path, 'message': exc.message})
        except GitHubAPIError as exc:
            errors.append({'path': path, 'message': exc.message})

    cache_key = f'{owner}/{repo}@{branch}'
    results = await semantic.rank_files(request, user, q, files, cache_key, top_k=max(1, min(max_results, 50)))
    await _audit(request, user.id, action='semantic_search', target=f'{owner}/{repo}', payload={'query': q[:200], 'results': len(results)}, db=db)
    return {'query': q, 'mode': results[0]['mode'] if results else 'lexical', 'results': results, 'errors': errors}


############################
# Review comments in PR (§22.2)
############################


@router.get('/pr/{owner}/{repo}/{pr_number}/comments')
async def coder_list_pr_comments(
    request: Request,
    owner: str,
    repo: str,
    pr_number: str,
    connection_id: str | None = None,
    user=Depends(get_verified_user),
    db: AsyncSession = Depends(get_async_session),
):
    """Список inline review-комментариев pull request."""
    await check_coder_permission(request, user)
    policies = await get_coder_policies()
    host = await _get_connection_host(user.id, db, connection_id)
    await _check_repo_access(request, policies, owner, repo, user.id, db, host)
    token = await _get_connection_token(user.id, db, connection_id)
    retry = _retry_settings_from_policies(policies)
    try:
        comments = await GitHubClient.list_pull_request_review_comments(token, owner, repo, pr_number, host=host)
    except GitHubAPIError as exc:
        raise HTTPException(status_code=exc.status_code or status.HTTP_502_BAD_GATEWAY, detail={'code': exc.code, 'message': exc.message})
    await _audit(request, user.id, action='review_comments_listed', target=f'{owner}/{repo}#{pr_number}', payload={'count': len(comments)}, db=db)
    return {'comments': comments}


@router.post('/pr/{owner}/{repo}/{pr_number}/comments')
async def coder_create_pr_comment(
    request: Request,
    owner: str,
    repo: str,
    pr_number: str,
    form: CoderReviewCommentForm,
    connection_id: str | None = None,
    user=Depends(get_verified_user),
    db: AsyncSession = Depends(get_async_session),
):
    """Создать inline review-комментарий к строке diff в PR."""
    await check_coder_permission(request, user)
    if form.owner != owner or form.repo != repo or str(form.pr_number) != str(pr_number):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail={'code': 'invalid_request', 'message': 'form fields do not match path'})
    policies = await get_coder_policies()
    host = await _get_connection_host(user.id, db, connection_id)
    await _check_repo_access(request, policies, owner, repo, user.id, db, host)
    try:
        safe_path = validate_path(form.path, policies['blocked_paths'])
    except ChangeSetValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail={'code': exc.code, 'message': exc.message})
    token = await _get_connection_token(user.id, db, connection_id)
    retry = _retry_settings_from_policies(policies)
    try:
        head_sha = await GitHubClient.get_pull_request_head_sha(token, owner, repo, pr_number, host=host)
        if not head_sha:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail={'code': 'CODER_PR_NOT_FOUND', 'message': 'Pull request not found'})
        comment = await GitHubClient.create_pull_request_review_comment(
            token, owner, repo, pr_number, head_sha, safe_path, form.line, form.body[:65536], form.side
        )
    except GitHubAPIError as exc:
        await _audit(request, user.id, action='permission_denied', target=f'{owner}/{repo}#{pr_number}', payload={'reason': 'github_api', 'code': exc.code}, db=db)
        raise HTTPException(status_code=exc.status_code or status.HTTP_502_BAD_GATEWAY, detail={'code': exc.code, 'message': exc.message})
    await _audit(request, user.id, action='review_comment_created', target=f'{owner}/{repo}#{pr_number}', payload={'path': safe_path, 'line': form.line}, db=db)
    return {'comment': comment}


############################
# CI statuses (§22.2)
############################


@router.get('/ci/status')
async def coder_ci_status(
    request: Request,
    owner: str,
    repo: str,
    branch: str,
    connection_id: str | None = None,
    user=Depends(get_verified_user),
    db: AsyncSession = Depends(get_async_session),
):
    """CI-статусы (check runs + commit statuses) для HEAD ветки репозитория."""
    await check_coder_permission(request, user)
    policies = await get_coder_policies()
    host = await _get_connection_host(user.id, db, connection_id)
    await _check_repo_access(request, policies, owner, repo, user.id, db, host)
    token = await _get_connection_token(user.id, db, connection_id)
    try:
        sha = await GitHubClient.get_ref_commit_sha(token, owner, repo, branch, host=host)
        status_payload = await GitHubClient.get_commit_check_status(token, owner, repo, sha, host=host)
    except GitHubAPIError as exc:
        raise HTTPException(status_code=exc.status_code or status.HTTP_502_BAD_GATEWAY, detail={'code': exc.code, 'message': exc.message})
    status_payload.update({'sha': sha, 'branch': branch})
    await _audit(request, user.id, action='ci_status_viewed', target=f'{owner}/{repo}@{branch}', payload={'state': status_payload.get('state')}, db=db)
    return status_payload


############################
# Export to Gist (§22.2)
############################


@router.post('/export/gist')
async def coder_export_gist(
    request: Request,
    form: CoderGistExportForm,
    user=Depends(get_verified_user),
    db: AsyncSession = Depends(get_async_session),
):
    """Экспорт файлов change set в GitHub Gist вместо коммита в репозиторий."""
    await check_coder_permission(request, user)
    if not form.files:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail={'code': 'invalid_request', 'message': 'files are required'})
    if len(form.files) > 50:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail={'code': 'CODER_TOO_MANY_FILES', 'message': 'A gist export supports at most 50 files'})
    policies = await get_coder_policies()
    sanitized: dict[str, str] = {}
    for raw_path, content in form.files.items():
        try:
            safe_path = validate_path(raw_path, policies['blocked_paths'])
        except ChangeSetValidationError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail={'code': exc.code, 'message': exc.message})
        sanitized[safe_path] = content
    token = await _get_connection_token(user.id, db)
    retry = _retry_settings_from_policies(policies)
    try:
        gist = await GitHubClient.create_gist(token, form.description or 'Coder export', sanitized, public=form.public, retry_settings=retry)
    except GitHubAPIError as exc:
        raise HTTPException(status_code=exc.status_code or status.HTTP_502_BAD_GATEWAY, detail={'code': exc.code, 'message': exc.message})
    await _audit(request, user.id, action='gist_exported', target=gist.get('html_url') or '', payload={'files': len(sanitized), 'public': form.public}, db=db)
    return {'gist': gist}


############################
# Auto-generated tests (§22.2)
############################


@router.post('/tests/suggest')
async def coder_tests_suggest(
    request: Request,
    form: CoderTestIssueForm,
    user=Depends(get_verified_user),
    db: AsyncSession = Depends(get_async_session),
):
    """Автогенерация теста: создать issue с шаблоном автотеста через LLM-модель сервера.

    Если модель недоступна — возвращается детерминированный шаблон pytest,
    который пользователь может положить в репозиторий обычным change set.
    """
    await check_coder_permission(request, user)
    policies = await get_coder_policies()
    await _check_repo_access(request, policies, form.owner, form.repo, user.id, db)

    prompt = (
        'Ты — инженер по тестированию. Сгенерируй пример автоматизированного теста '
        '(pytest или эквивалент для языка проекта) для следующей задачи:\n\n'
        f"Название: {form.title}\n{form.body or ''}\n\n"
        'Ответь только блоком кода и коротким пояснением.'
    )
    generated = None
    try:
        from open_webui.models.models import Models
        from open_webui.apps.webui.internal.db import Session  # noqa: F401  (ensure DB ready)
        from open_webui.utils.models import get_default_model_id  # type: ignore

        default_model = get_default_model_id()
    except Exception:
        default_model = None
    if default_model:
        try:
            from open_webui.tasks import chat_completion_handler  # type: ignore

            result = await chat_completion_handler(
                request,
                {
                    'model': default_model,
                    'messages': [{'role': 'user', 'content': prompt}],
                    'stream': False,
                },
                user_id=user.id,
                model_id=default_model,
            )
            if isinstance(result, dict):
                choices = result.get('choices') or []
                if choices:
                    generated = ((choices[0].get('message') or {}).get('content')) or None
        except Exception:
            log.debug('coder test suggestion generation failed', exc_info=True)

    template = generated or (
        f'"""Auto-generated test skeleton for: {form.title}"""\n\n'
        'import pytest\n\n\n'
        '@pytest.mark.skip(reason="TODO: implement assertions")\n'
        'def test_placeholder():\n'
        '    assert True\n'
    )

    token = await _get_connection_token(user.id, db)
    retry = _retry_settings_from_policies(policies)
    body = (
        f"Сгенерировано секцией Coder пользователем @{user.id[:8]}…\n\n{form.body or ''}\n\n"
        f'### Предлагаемый тест\n\n```python\n{template[:60000]}\n```\n'
    )
    try:
        issue = await GitHubClient.create_issue(token, form.owner, form.repo, f'[tests] {form.title}'[:250], body, form.labels[:10], retry_settings=retry)
    except GitHubAPIError as exc:
        raise HTTPException(status_code=exc.status_code or status.HTTP_502_BAD_GATEWAY, detail={'code': exc.code, 'message': exc.message})
    await _audit(request, user.id, action='test_issue_created', target=f'{form.owner}/{form.repo}', payload={'issue': issue.get('number'), 'llm_generated': bool(generated)}, db=db)
    return {'issue': issue, 'test_template': template, 'generated_by_model': bool(generated)}


############################
# Change Set validation / preview
############################


@router.post('/changeset/validate')
async def coder_validate_changeset(
    request: Request,
    form: CoderChangeSetForm,
    user=Depends(get_verified_user),
    db: AsyncSession = Depends(get_async_session),
):
    await check_coder_permission(request, user)
    try:
        normalized = validate_changeset(form.files)
    except ChangeSetValidationError as exc:
        return {
            'valid': False,
            'error': {'code': exc.code, 'message': exc.message, 'path': exc.path},
        }
    return {'valid': True, 'changeset': normalized, 'file_count': len(normalized['files'])}


@router.post('/export/preview')
async def coder_export_preview(
    request: Request,
    form: CoderExportForm,
    user=Depends(get_verified_user),
    db: AsyncSession = Depends(get_async_session),
):
    """Validate change set against the live repository and produce unified diffs."""
    await check_coder_permission(request, user)
    policies = await get_coder_policies()
    host = await _get_connection_host(user.id, db, form.connection_id)
    await _check_repo_access(request, policies, form.owner, form.repo, user.id, db, host)
    try:
        normalized = validate_changeset(form.changeset.files, repo=f"{form.owner}/{form.repo}", policies=policies)
    except ChangeSetValidationError as exc:
        await _audit(request, user.id, action='permission_denied', target=f'{form.owner}/{form.repo}', payload={'reason': exc.code, 'where': 'export/preview'}, db=db)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={'code': exc.code, 'message': exc.message, 'path': exc.path},
        )

    token = await _get_connection_token(user.id, db, form.connection_id)
    diffs = []
    errors = []
    for entry in normalized['files']:
        old_content = None
        try:
            existing = await GitHubClient.get_file(token, form.owner, form.repo, entry['path'], form.base_branch, host=host)
            old_content = existing.get('content')
            exists = not existing.get('binary')
        except GitHubAPIError as exc:
            if exc.code == 'CODER_NOT_FOUND':
                exists = False
            else:
                errors.append({'path': entry['path'], 'code': exc.code, 'message': exc.message})
                continue

        if entry['action'] in ('update', 'delete') and not exists:
            errors.append({'path': entry['path'], 'code': 'CODER_FILE_NOT_FOUND', 'message': 'File does not exist in base branch'})
            continue
        if entry['action'] == 'create' and exists:
            errors.append({'path': entry['path'], 'code': 'CODER_FILE_EXISTS', 'message': 'File already exists in base branch'})
            continue

        diff = generate_unified_diff(old_content, entry['content'], entry['path'])
        diffs.append({'path': entry['path'], 'action': entry['action'], 'diff': diff})

    await _audit(
        request, user.id, action='diff_generated', target=f'{form.owner}/{form.repo}',
        payload={'files': len(diffs), 'errors': len(errors), 'branch': form.base_branch}, db=db,
    )
    return {'valid': len(errors) == 0, 'diffs': diffs, 'errors': errors}


############################
# Export jobs
############################


@router.post('/export/start')
async def coder_export_start(
    request: Request,
    form: CoderExportForm,
    user=Depends(get_verified_user),
    db: AsyncSession = Depends(get_async_session),
):
    """Create an export job and execute it synchronously (Git Data API + mandatory PR)."""
    await check_coder_permission(request, user)

    # idempotency: return existing job if key was seen
    existing = await CoderExportJobs.get_by_idempotency_key(form.idempotency_key, db)
    if existing:
        return {'job_id': existing.id, 'status': existing.status, 'replayed': True}

    try:
        normalized = validate_changeset(form.changeset.files, repo=f"{form.owner}/{form.repo}")
    except ChangeSetValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={'code': exc.code, 'message': exc.message, 'path': exc.path},
        )

    policies = await get_coder_policies()
    host = await _get_connection_host(user.id, db, form.connection_id)
    await _check_repo_access(request, policies, form.owner, form.repo, user.id, db, host)
    token = await _get_connection_token(user.id, db, form.connection_id)

    project = await CoderProjects.get_by_user_repo(user.id, form.owner, form.repo, db)
    job = await CoderExportJobs.create(
        user_id=user.id,
        owner=form.owner,
        repo=form.repo,
        base_branch=form.base_branch,
        branch=form.branch,
        commit_message=form.commit_message,
        changeset=normalized,
        idempotency_key=form.idempotency_key,
        project_id=project.id if project else None,
        db=db,
    )
    await _audit(
        request,
        user_id=user.id,
        action='export_start',
        target=f'{form.owner}/{form.repo}:{form.branch}',
        payload={'job_id': job.id, 'file_count': len(normalized['files'])},
        db=db,
    )

    try:
        await _run_export_job(job.id, token, form, normalized, user.id, db, host=host)
    except HTTPException as http_exc:
        # structured error from _run_export_job (e.g. missing repo scopes) — mark failed, pass through
        detail = http_exc.detail if isinstance(http_exc.detail, dict) else {}
        await CoderExportJobs.update(
            job.id,
            {'status': 'failed', 'error': f"{detail.get('code', 'CODER_EXPORT_FAILED')}: {detail.get('message', '')}"},
            db,
        )
        await _audit(
            request,
            user_id=user.id,
            action='export_failed',
            target=f'{form.owner}/{form.repo}:{form.branch}',
            payload={'job_id': job.id, 'code': detail.get('code')},
            db=db,
        )
        raise
    except GitHubAPIError as exc:
        await CoderExportJobs.update(job.id, {'status': 'failed', 'error': f'{exc.code}: {exc.message}'}, db)
        await _audit(
            request,
            user_id=user.id,
            action='export_failed',
            target=f'{form.owner}/{form.repo}:{form.branch}',
            payload={'job_id': job.id, 'code': exc.code},
            db=db,
        )
        raise HTTPException(status_code=exc.status_code or status.HTTP_502_BAD_GATEWAY, detail={'code': exc.code, 'message': exc.message})
    except Exception as exc:
        log.exception('Coder export job failed unexpectedly')
        await CoderExportJobs.update(job.id, {'status': 'failed', 'error': str(exc)}, db)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={'code': 'CODER_EXPORT_FAILED', 'message': 'Export failed'},
        )

    refreshed = await CoderExportJobs.get_by_id(job.id, db)
    await _audit(
        request,
        user_id=user.id,
        action='export_completed',
        target=f'{form.owner}/{form.repo}:{form.branch}',
        payload={'job_id': job.id, 'commit_sha': refreshed.commit_sha, 'pr_url': refreshed.pr_url},
        db=db,
    )
    return {
        'job_id': refreshed.id,
        'status': refreshed.status,
        'commit_sha': refreshed.commit_sha,
        'pr_url': refreshed.pr_url,
        'pr_number': refreshed.pr_number,
    }


async def _run_export_job(job_id: str, token: str, form: CoderExportForm, normalized: dict, user_id: str, db: AsyncSession, host: str | None = None):
    await CoderExportJobs.update(job_id, {'status': 'running'}, db)

    owner, repo = form.owner, form.repo

    # Fail fast with a clear message if the OAuth token lacks write access to this repo
    # (otherwise GitHub returns an opaque 404/403 during ref creation).
    try:
        from open_webui.utils.coder.github_client import _api_base

        perms_response = await github_request(
            'GET', f'{_api_base(host)}/repos/{quote(owner)}/{quote(repo)}', token=token
        )
        if perms_response.status_code == 200:
            pdata = perms_response.json()
            push_allowed = bool((pdata.get('permissions') or {}).get('push'))
            if not push_allowed:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail={
                        'code': 'CODER_FORBIDDEN',
                        'message': f'Your GitHub token does not have write access to {owner}/{repo}. '
                        'Check repository roles/app installation permissions and reconnect GitHub in the Environment tab.',
                    },
                )
    except GitHubAPIError as exc:
        if exc.code == 'CODER_NOT_FOUND':
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={
                    'code': 'CODER_NOT_FOUND',
                    'message': f'Repository {owner}/{repo} is not accessible with your GitHub token '
                    '(deleted, renamed, or outside the granted scopes). Reconnect GitHub in the Environment tab.',
                },
            )
        raise

    base_sha = await GitHubClient.get_ref_commit_sha(token, owner, repo, form.base_branch, host=host)

    # create or reset working branch from base
    try:
        await GitHubClient.get_ref_commit_sha(token, owner, repo, form.branch, host=host)
        branch_exists = True
    except GitHubAPIError as exc:
        if exc.code == 'CODER_NOT_FOUND':
            branch_exists = False
        else:
            raise

    entries = []
    for entry in normalized['files']:
        if entry['action'] == 'delete':
            entries.append({'path': entry['path'], 'mode': '100644', 'type': 'blob', 'sha': None})
        else:
            blob_sha = await GitHubClient.create_blob(token, owner, repo, entry['content'], host=host)
            entries.append({'path': entry['path'], 'mode': '100644', 'type': 'blob', 'sha': blob_sha})

    tree_sha = await GitHubClient.create_tree(token, owner, repo, base_sha, entries, host=host)
    commit_sha = await GitHubClient.create_commit(token, owner, repo, tree_sha, base_sha, form.commit_message, host=host)

    if branch_exists:
        await GitHubClient.update_ref(token, owner, repo, form.branch, commit_sha, force=False, host=host)
    else:
        await GitHubClient.create_ref(token, owner, repo, form.branch, commit_sha, host=host)

    pr = await GitHubClient.create_pull_request(
        token,
        owner,
        repo,
        host=host,
        title=form.commit_message[:200],
        head=form.branch,
        base=form.base_branch,
        body='Created by Open WebUI Coder.',
    )

    await CoderExportJobs.update(
        job_id,
        {'status': 'completed', 'commit_sha': commit_sha, 'pr_url': pr['html_url'], 'pr_number': pr['number']},
        db,
    )


@router.get('/export/jobs')
async def coder_export_jobs(request: Request, user=Depends(get_verified_user), db: AsyncSession = Depends(get_async_session)):
    await check_coder_permission(request, user)
    jobs = await CoderExportJobs.list_by_user_id(user.id, db)
    return {
        'jobs': [
            {
                'id': j.id,
                'owner': j.owner,
                'repo': j.repo,
                'base_branch': j.base_branch,
                'branch': j.branch,
                'status': j.status,
                'error': j.error,
                'commit_sha': j.commit_sha,
                'pr_url': j.pr_url,
                'pr_number': j.pr_number,
                'created_at': j.created_at,
            }
            for j in jobs
        ]
    }


@router.get('/export/jobs/{job_id}')
async def coder_export_job(job_id: str, request: Request, user=Depends(get_verified_user), db: AsyncSession = Depends(get_async_session)):
    await check_coder_permission(request, user)
    job = await CoderExportJobs.get_by_id(job_id, db)
    if not job or job.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=ERROR_MESSAGES.NOT_FOUND)
    return {
        'id': job.id,
        'status': job.status,
        'error': job.error,
        'commit_sha': job.commit_sha,
        'pr_url': job.pr_url,
        'pr_number': job.pr_number,
        'created_at': job.created_at,
        'updated_at': job.updated_at,
    }


############################
# Audit
############################


@router.get('/audit')
async def coder_audit(request: Request, user=Depends(get_verified_user), db: AsyncSession = Depends(get_async_session)):
    await check_coder_permission(request, user)
    events = await CoderAudit.list_by_user_id(user.id, db)
    return {
        'events': [
            {'id': e.id, 'action': e.action, 'target': e.target, 'payload': e.payload, 'created_at': e.created_at}
            for e in events
        ]
    }


@router.get('/admin/audit')
async def coder_admin_audit(
    request: Request,
    limit: int = 200,
    user=Depends(get_admin_user),
    db: AsyncSession = Depends(get_async_session),
):
    """Admin overview of audit events across all users (§14.1)."""
    await check_coder_permission(request, user)
    events = await CoderAudit.list_all(db, limit=max(1, min(limit, 1000)))
    return {
        'events': [
            {
                'id': e.id,
                'user_id': e.user_id,
                'action': e.action,
                'target': e.target,
                'payload': e.payload,
                'correlation_id': getattr(e, 'correlation_id', None),
                'ip_address': getattr(e, 'ip_address', None),
                'created_at': e.created_at,
            }
            for e in events
        ]
    }


@router.post('/audit/cleanup')
async def coder_audit_cleanup(request: Request, user=Depends(get_verified_user), db: AsyncSession = Depends(get_async_session)):
    """Admin endpoint to cleanup old audit events."""
    # Only admins can cleanup audit logs
    if user.get('role') != 'admin':
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=ERROR_MESSAGES.UNAUTHORIZED)

    # Get retention days from config, fallback to env var default
    retention_days = await Config.get('coder.audit_retention_days', CODER_AUDIT_RETENTION_DAYS)
    deleted_count = await CoderAudit.cleanup_old_events(retention_days, db)

    return {
        'message': 'Audit cleanup completed',
        'deleted_count': deleted_count,
        'retention_days': retention_days,
    }


############################
# Projects (saved repositories)
############################


class CoderProjectCreateForm(BaseModel):
    owner: str
    repo: str
    default_branch: str | None = None
    name: str | None = None


def _project_payload(project) -> dict:
    meta = project.meta or {}
    return {
        'id': project.id,
        'owner': project.owner,
        'repo': project.repo,
        'name': meta.get('name'),
        'default_branch': project.default_branch,
        'created_at': project.created_at,
        'updated_at': project.updated_at,
    }


@router.get('/projects')
async def coder_list_projects(request: Request, user=Depends(get_verified_user), db: AsyncSession = Depends(get_async_session)):
    """Coder -> Projects tab: list saved projects for the current user."""
    await check_coder_permission(request, user)
    projects = await CoderProjects.list_by_user_id(user.id, db)
    await _audit(request, user.id, action='section_accessed', target='projects', db=db)
    return {'projects': [_project_payload(p) for p in projects]}


@router.post('/projects')
async def coder_create_project(
    request: Request,
    form_data: CoderProjectCreateForm,
    user=Depends(get_verified_user),
    db: AsyncSession = Depends(get_async_session),
):
    await check_coder_permission(request, user)
    owner = form_data.owner.strip()
    repo = form_data.repo.strip()
    if not owner or not repo:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={'code': 'CODER_INVALID_PROJECT', 'message': 'Project requires an owner and a repository name'},
        )
    policies = await get_coder_policies()
    await _check_repo_access(request, policies, owner, repo, user.id, db)

    project = await CoderProjects.upsert(
        user.id,
        CoderProjectForm(owner=owner, repo=repo, default_branch=form_data.default_branch),
        db,
    )
    # store optional display name in meta
    if form_data.name:
        meta = dict(project.meta or {})
        meta['name'] = form_data.name
        project.meta = meta
        project.updated_at = int(time.time())
        await db.flush()
    await _audit(request, user.id, action='project_created', target=f'{owner}/{repo}', payload={'project_id': project.id}, db=db)
    return _project_payload(project)


@router.get('/projects/{project_id}')
async def coder_get_project(request: Request, project_id: str, user=Depends(get_verified_user), db: AsyncSession = Depends(get_async_session)):
    await check_coder_permission(request, user)
    project = await CoderProjects.get_by_id(project_id, db)
    if not project or project.user_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={'code': 'CODER_PROJECT_NOT_FOUND', 'message': 'Project not found'},
        )
    return _project_payload(project)


@router.delete('/projects/{project_id}')
async def coder_delete_project(request: Request, project_id: str, user=Depends(get_verified_user), db: AsyncSession = Depends(get_async_session)):
    await check_coder_permission(request, user)
    project = await CoderProjects.get_by_id(project_id, db)
    if not project or project.user_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={'code': 'CODER_PROJECT_NOT_FOUND', 'message': 'Project not found'},
        )
    await CoderProjects.delete(project_id, db)
    await _audit(request, user.id, action='project_deleted', target=f'{project.owner}/{project.repo}', payload={'project_id': project_id}, db=db)
    return {'status': True}


####################
# Sandbox / Preview / Publish (план coder.qwen.ai §A)
####################


class CoderSandboxWriteForm(BaseModel):
    path: str
    content: str


class CoderSandboxChangesetForm(BaseModel):
    files: list[dict[str, Any]]


def _sandbox_error(exc: SandboxError) -> HTTPException:
    code = status.HTTP_400_BAD_REQUEST
    if exc.code == 'not_found':
        code = status.HTTP_404_NOT_FOUND
    elif exc.code in ('quota_exceeded', 'too_large'):
        code = status.HTTP_413_REQUEST_ENTITY_TOO_LARGE
    return HTTPException(status_code=code, detail={'code': f'SANDBOX_{exc.code.upper()}', 'message': str(exc)})


async def _get_sandbox_session(request: Request, user, session_id: str, db: AsyncSession):
    await check_coder_permission(request, user)
    session = await CoderSandboxSessions.get_by_id(session_id, db)
    if not session or session.user_id != user.id or session.status == 'destroyed':
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={'code': 'CODER_SANDBOX_NOT_FOUND', 'message': 'Sandbox session not found'},
        )
    return session


@router.get('/modes')
async def coder_modes_list(request: Request, user=Depends(get_verified_user), db: AsyncSession = Depends(get_async_session)):
    """§B1: список режимов генерации; §B2: галерея шаблонов."""
    await check_coder_permission(request, user)
    return {'modes': coder_modes.list_modes(), 'templates': coder_modes.list_templates()}


@router.post('/sandbox/session')
async def coder_sandbox_create(
    request: Request,
    form: CoderSandboxCreateForm,
    user=Depends(get_verified_user),
    db: AsyncSession = Depends(get_async_session),
):
    """§A1: создать изолированный sandbox на задачу (create → active)."""
    await check_coder_permission(request, user)
    session = await CoderSandboxSessions.create(user.id, mode=form.mode, db=db)
    skeleton = {}
    template = coder_modes.get_template(form.template_id) if form.template_id else None
    if template:
        skeleton = coder_modes.skeleton_for(template['mode'])
    elif form.mode:
        skeleton = coder_modes.skeleton_for(form.mode)
    try:
        coder_sandbox.create_sandbox(session.id, skeleton)
    except SandboxError as exc:
        await CoderSandboxSessions.update(session.id, {'status': 'destroyed'}, db)
        raise _sandbox_error(exc)
    await _audit(
        request, user.id, action='sandbox_created', target=session.id,
        payload={'mode': form.mode, 'template_id': form.template_id}, db=db,
    )
    return CoderSandboxSessionModel.model_validate(session).model_dump()


@router.get('/sandbox/sessions')
async def coder_sandbox_list(request: Request, user=Depends(get_verified_user), db: AsyncSession = Depends(get_async_session)):
    await check_coder_permission(request, user)
    sessions = await CoderSandboxSessions.list_by_user_id(user.id, db, statuses=['active', 'paused'])
    return [CoderSandboxSessionModel.model_validate(s).model_dump() for s in sessions]


@router.get('/sandbox/session/{session_id}')
async def coder_sandbox_get(request: Request, session_id: str, user=Depends(get_verified_user), db: AsyncSession = Depends(get_async_session)):
    session = await _get_sandbox_session(request, user, session_id, db)
    try:
        files = coder_sandbox.list_files(session_id)
    except SandboxError as exc:
        raise _sandbox_error(exc)
    payload = CoderSandboxSessionModel.model_validate(session).model_dump()
    payload['files'] = files
    return payload


@router.post('/sandbox/session/{session_id}/pause')
async def coder_sandbox_pause(request: Request, session_id: str, user=Depends(get_verified_user), db: AsyncSession = Depends(get_async_session)):
    """§A1 жизненный цикл pause/resume."""
    session = await _get_sandbox_session(request, user, session_id, db)
    session = await CoderSandboxSessions.update(session_id, {'status': 'paused'}, db)
    return CoderSandboxSessionModel.model_validate(session).model_dump()


@router.post('/sandbox/session/{session_id}/resume')
async def coder_sandbox_resume(request: Request, session_id: str, user=Depends(get_verified_user), db: AsyncSession = Depends(get_async_session)):
    session = await _get_sandbox_session(request, user, session_id, db)
    session = await CoderSandboxSessions.update(session_id, {'status': 'active'}, db)
    await CoderSandboxSessions.touch(session_id, db)
    return CoderSandboxSessionModel.model_validate(session).model_dump()


@router.delete('/sandbox/session/{session_id}')
async def coder_sandbox_destroy(request: Request, session_id: str, user=Depends(get_verified_user), db: AsyncSession = Depends(get_async_session)):
    """§A1 destroy: удаляет директорию песочницы и помечает сессию."""
    await _get_sandbox_session(request, user, session_id, db)
    removed = False
    try:
        removed = coder_sandbox.destroy_sandbox(session_id)
    except SandboxError:
        pass
    await CoderSandboxSessions.update(session_id, {'status': 'destroyed'}, db)
    await _audit(request, user.id, action='sandbox_destroyed', target=session_id, payload={'removed_dir': removed}, db=db)
    return {'status': True}


@router.get('/sandbox/session/{session_id}/file')
async def coder_sandbox_read_file(
    request: Request, session_id: str, path: str,
    user=Depends(get_verified_user), db: AsyncSession = Depends(get_async_session),
):
    """§A3: чтение файла из sandbox для браузерного редактора."""
    await _get_sandbox_session(request, user, session_id, db)
    try:
        content, mime = coder_sandbox.read_file(session_id, path)
    except SandboxError as exc:
        raise _sandbox_error(exc)
    return {'path': path, 'content': content, 'mime': mime}


@router.put('/sandbox/session/{session_id}/file')
async def coder_sandbox_write_file(
    request: Request, session_id: str, form: CoderSandboxWriteForm,
    user=Depends(get_verified_user), db: AsyncSession = Depends(get_async_session),
):
    await _get_sandbox_session(request, user, session_id, db)
    try:
        info = coder_sandbox.write_file(session_id, form.path, form.content)
    except SandboxError as exc:
        raise _sandbox_error(exc)
    await CoderSandboxSessions.touch(session_id, db)
    return info


@router.delete('/sandbox/session/{session_id}/file')
async def coder_sandbox_delete_file(
    request: Request, session_id: str, path: str,
    user=Depends(get_verified_user), db: AsyncSession = Depends(get_async_session),
):
    await _get_sandbox_session(request, user, session_id, db)
    try:
        ok = coder_sandbox.delete_file(session_id, path)
    except SandboxError as exc:
        raise _sandbox_error(exc)
    await CoderSandboxSessions.touch(session_id, db)
    return {'status': ok}


@router.post('/sandbox/session/{session_id}/changeset')
async def coder_sandbox_apply_changeset(
    request: Request, session_id: str, form: CoderSandboxChangesetForm,
    user=Depends(get_verified_user), db: AsyncSession = Depends(get_async_session),
):
    """Применяет change set модели к sandbox (§A5: Stop откатывает только не применённые файлы)."""
    await _get_sandbox_session(request, user, session_id, db)
    try:
        applied = coder_sandbox.apply_changeset(session_id, form.files)
    except SandboxError as exc:
        raise _sandbox_error(exc)
    await CoderSandboxSessions.touch(session_id, db)
    await _audit(request, user.id, action='sandbox_changeset_applied', target=session_id, payload={'files': len(applied)}, db=db)
    return {'applied': applied}


@router.get('/sandbox/session/{session_id}/preview', response_class=PlainTextResponse)
async def coder_sandbox_preview(
    request: Request, session_id: str, v: int | None = None,
    user=Depends(get_verified_user), db: AsyncSession = Depends(get_async_session),
):
    """§A2: HTML живой превью-панели (iframe src). v — cache-buster для hot-reload."""
    await _get_sandbox_session(request, user, session_id, db)
    try:
        html = coder_sandbox.get_preview_html(session_id)
    except SandboxError as exc:
        raise _sandbox_error(exc)
    await CoderSandboxSessions.touch(session_id, db)
    return PlainTextResponse(html, media_type='text/html; charset=utf-8')


@router.post('/sandbox/session/{session_id}/publish')
async def coder_sandbox_publish(request: Request, session_id: str, user=Depends(get_verified_user), db: AsyncSession = Depends(get_async_session)):
    """§A4: публикация одним кликом — копия проекта в published/<share_id>."""
    session = await _get_sandbox_session(request, user, session_id, db)
    share_id = session.published_share_id or session_id
    try:
        result = coder_sandbox.publish_sandbox(session_id, share_id)
    except SandboxError as exc:
        raise _sandbox_error(exc)
    await CoderSandboxSessions.update(session_id, {'published_share_id': share_id}, db)
    await _audit(request, user.id, action='sandbox_published', target=share_id, payload=result, db=db)
    from open_webui.config import CODER_PUBLISH_URL_PREFIX

    return {'share_id': share_id, 'url': f'{CODER_PUBLISH_URL_PREFIX}/s/{share_id}', **result}


@router.get('/preview/s/{share_id}', response_class=PlainTextResponse)
async def coder_published_page(request: Request, share_id: str):
    """Публичная страница результата по share_id (аналог /c/<id> у Qwen, без авторизации)."""
    config = await Config.get_many('coder.enable')
    if not config.get('coder.enable', CODER_ENABLED):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=ERROR_MESSAGES.UNAUTHORIZED)
    try:
        html = coder_sandbox.read_published(share_id)
    except SandboxError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={'code': 'CODER_PUBLISH_NOT_FOUND', 'message': 'Published page not found'},
        )
    return PlainTextResponse(html, media_type='text/html; charset=utf-8')


@router.post('/sandbox/sweep')
async def coder_sandbox_sweep(request: Request, admin_user=Depends(get_admin_user), db: AsyncSession = Depends(get_async_session)):
    """§A1 TTL-чистка протухших sandbox-сессий (запускается админом/крон-задачей).

    Удаляет строки БД старше TTL и осиротевшие директории внутри sandbox root.
    """
    from open_webui.config import CODER_SANDBOX_TTL_MINUTES

    ttl = CODER_SANDBOX_TTL_MINUTES * 60
    removed_rows = await CoderSandboxSessions.delete_expired(ttl, db)
    removed_dirs = 0
    try:
        # список живых id из БД (все пользователи) — через прямой select
        live_ids = {row[0] for row in await db.execute(sa_select(CoderSandboxSession.id))}
        for d in coder_sandbox.sandbox_root().iterdir():
            if not d.is_dir() or not coder_sandbox.SAFE_SESSION_ID.match(d.name):
                continue
            stale = (time.time() - d.stat().st_mtime) > ttl
            if stale and d.name not in live_ids:
                try:
                    coder_sandbox.destroy_sandbox(d.name)
                    removed_dirs += 1
                except SandboxError:
                    pass
        await db.commit()
    except Exception:
        log.debug('coder sandbox dir sweep failed', exc_info=True)
    await _audit(request, admin_user.id, action='sandbox_sweep', payload={'expired_rows': removed_rows, 'removed_dirs': removed_dirs}, db=db)
    return {'expired_rows': removed_rows, 'removed_dirs': removed_dirs}


####################
# Task meta: pin/archive/search/title-tags/followups (план §B3/B4, §C)
####################


@router.get('/tasks')
async def coder_tasks_list(
    request: Request,
    archived: bool = False,
    q: str | None = None,
    tag: str | None = None,
    user=Depends(get_verified_user),
    db: AsyncSession = Depends(get_async_session),
):
    """§C1/C2: список задач с pin-сортировкой, фильтром архива и глобальным поиском."""
    await check_coder_permission(request, user)
    rows = await CoderTaskMetas.list_by_user_id(user.id, db, include_archived=archived, search=q, tag=tag)
    return [CoderTaskMetaModel.model_validate(r).model_dump() for r in rows]


@router.post('/tasks/{chat_id}')
async def coder_tasks_upsert(
    request: Request, chat_id: str, form: CoderTaskMetaForm,
    user=Depends(get_verified_user), db: AsyncSession = Depends(get_async_session),
):
    """§C1 pin/unpin/archive/restore + ручные title/tags/mode/status."""
    await check_coder_permission(request, user)
    row = await CoderTaskMetas.upsert(user.id, chat_id, form, db)
    await _audit(request, user.id, action='task_meta_updated', target=chat_id, payload=form.model_dump(exclude_none=True), db=db)
    return CoderTaskMetaModel.model_validate(row).model_dump()


@router.delete('/tasks/{chat_id}')
async def coder_tasks_delete(request: Request, chat_id: str, user=Depends(get_verified_user), db: AsyncSession = Depends(get_async_session)):
    await check_coder_permission(request, user)
    ok = await CoderTaskMetas.delete_by_chat(user.id, chat_id, db)
    return {'status': ok}


@router.post('/tasks/{chat_id}/title')
async def coder_task_title(
    request: Request, chat_id: str, prompt: str = '',
    user=Depends(get_verified_user), db: AsyncSession = Depends(get_async_session),
):
    """§B3: автосохранение названия и тегов задачи (быстрая эвристика, аналог /api/task/title|tags)."""
    await check_coder_permission(request, user)
    title, tags = coder_modes.derive_title_and_tags(prompt or '')
    row = await CoderTaskMetas.upsert(user.id, chat_id, CoderTaskMetaForm(title=title, tags=tags), db)
    return {'title': row.title, 'tags': row.tags}


@router.get('/tasks/{chat_id}/followups')
async def coder_task_followups(request: Request, chat_id: str, mode: str | None = None, user=Depends(get_verified_user)):
    """§B4: follow-up предложения «что сделать дальше»."""
    await check_coder_permission(request, user)
    return {'suggestions': coder_modes.followup_suggestions(mode)}


@router.post('/stream/metrics')
async def coder_stream_metrics(
    request: Request,
    first_chunk_ms: float | None = None,
    chunks: int = 0,
    mode: str = 'default',
    user=Depends(get_verified_user),
    db: AsyncSession = Depends(get_async_session),
):
    """§E2: UI сообщает о времени первого чанка и количестве чанков стрима."""
    await check_coder_permission(request, user)
    first_chunk_s = (first_chunk_ms / 1000.0) if first_chunk_ms is not None else None
    observe_stream(first_chunk_seconds=first_chunk_s, chunks=chunks, mode=mode)
    await _audit(
        request, user.id, action='generation_streamed', target=mode,
        payload={'first_chunk_ms': first_chunk_ms, 'chunks': chunks}, db=db,
    )
    return {'status': True}
