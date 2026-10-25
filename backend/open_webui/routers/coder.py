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
from fastapi.responses import RedirectResponse
from open_webui.config import CODER_ENABLED, CODER_GITHUB_CLIENT_ID, CODER_AUDIT_RETENTION_DAYS, WEBUI_URL
from open_webui.constants import ERROR_MESSAGES
from open_webui.internal.db import get_async_session
from open_webui.models.coder import (
    CoderAudit,
    CoderExportForm,
    CoderGithubConnections,
    CoderProjects,
    CoderExportJobs,
)
from open_webui.models.config import Config
from open_webui.utils.auth import get_verified_user
from open_webui.utils.coder.changeset import ChangeSetValidationError, generate_unified_diff, validate_changeset, validate_path
from open_webui.utils.coder.crypto import decrypt_secret, encrypt_secret
from open_webui.utils.coder.github_client import GitHubAPIError, GitHubClient, _request as github_request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

log = logging.getLogger(__name__)

router = APIRouter()

OAUTH_STATE_TTL_SECONDS = 600
# in-memory CSRF state store: state -> {user_id, expires}
_oauth_states: dict[str, dict] = {}


class CoderChangeSetForm(BaseModel):
    files: list[dict[str, Any]]


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
    except Exception:
        log.debug('coder audit record failed', exc_info=True)


async def _get_connection_token(user_id: str, db: AsyncSession) -> str:
    connection = await CoderGithubConnections.get_by_user_id(user_id, db)
    if not connection:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={'code': 'CODER_NOT_CONNECTED', 'message': 'GitHub account is not connected'},
        )
    try:
        token = decrypt_secret(connection.access_token_encrypted)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={'code': 'CODER_DECRYPTION_FAILED', 'message': 'Failed to decrypt stored GitHub token'},
        )
    return token


def _prune_oauth_states():
    now = time.time()
    expired = [k for k, v in _oauth_states.items() if v['expires'] < now]
    for k in expired:
        _oauth_states.pop(k, None)


############################
# Config
############################


@router.get('/config')
async def get_coder_config(user=Depends(get_verified_user)):
    return {
        'enabled': CODER_ENABLED,
        'github_oauth_configured': bool(CODER_GITHUB_CLIENT_ID),
        'github_client_id': CODER_GITHUB_CLIENT_ID or None,
    }


############################
# GitHub OAuth
############################


@router.get('/github/auth/start')
async def github_auth_start(request: Request, user=Depends(get_verified_user)):
    await check_coder_permission(request, user)
    if not CODER_GITHUB_CLIENT_ID:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={'code': 'CODER_OAUTH_NOT_CONFIGURED', 'message': 'GitHub OAuth is not configured on this server'},
        )
    _prune_oauth_states()
    state = secrets.token_urlsafe(32)
    _oauth_states[state] = {'user_id': user.id, 'expires': time.time() + OAUTH_STATE_TTL_SECONDS}

    redirect_uri = str(request.url_for('github_auth_callback'))
    authorize_url = (
        f'https://github.com/login/oauth/authorize'
        f'?client_id={CODER_GITHUB_CLIENT_ID}'
        f'&redirect_uri={redirect_uri}'
        f'&scope=repo'
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

    try:
        token_data = await GitHubClient.exchange_code(code)
        gh_user = await GitHubClient.get_user(token_data['access_token'])
    except GitHubAPIError as exc:
        log.exception('Coder GitHub OAuth callback failed')
        return RedirectResponse(url=_coder_redirect_url(request, 'github_error=api_failure'), status_code=302)

    encrypted = encrypt_secret(token_data['access_token'])
    await CoderGithubConnections.upsert(
        user_id=user_id,
        github_login=gh_user['login'],
        github_user_id=gh_user['id'],
        access_token_encrypted=encrypted,
        scopes=token_data['scope'],
        db=db,
    )
    await _audit(request, user_id, action='github_connect', target=gh_user['login'], db=db)
    await db.commit()
    return RedirectResponse(url=_coder_redirect_url(request, 'github_connected=1'), status_code=302)


@router.get('/github/connection')
async def github_connection(request: Request, user=Depends(get_verified_user), db: AsyncSession = Depends(get_async_session)):
    await check_coder_permission(request, user)
    connection = await CoderGithubConnections.get_by_user_id(user.id, db)
    if not connection:
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


############################
# Repositories / branches / tree / file
############################


@router.get('/repos')
async def coder_repos(
    request: Request,
    query: str | None = None,
    page: int = 1,
    user=Depends(get_verified_user),
    db: AsyncSession = Depends(get_async_session),
):
    await check_coder_permission(request, user)
    token = await _get_connection_token(user.id, db)
    try:
        repos = await GitHubClient.list_repositories(token, query=query, page=page)
    except GitHubAPIError as exc:
        raise HTTPException(status_code=exc.status_code or status.HTTP_502_BAD_GATEWAY, detail={'code': exc.code, 'message': exc.message})
    return {'repos': repos}


@router.get('/branches')
async def coder_branches(
    request: Request,
    owner: str,
    repo: str,
    user=Depends(get_verified_user),
    db: AsyncSession = Depends(get_async_session),
):
    await check_coder_permission(request, user)
    token = await _get_connection_token(user.id, db)
    try:
        branches = await GitHubClient.list_branches(token, owner, repo)
    except GitHubAPIError as exc:
        raise HTTPException(status_code=exc.status_code or status.HTTP_502_BAD_GATEWAY, detail={'code': exc.code, 'message': exc.message})
    return {'branches': branches}


@router.get('/tree')
async def coder_tree(
    request: Request,
    owner: str,
    repo: str,
    branch: str,
    user=Depends(get_verified_user),
    db: AsyncSession = Depends(get_async_session),
):
    await check_coder_permission(request, user)
    token = await _get_connection_token(user.id, db)
    try:
        tree = await GitHubClient.get_tree(token, owner, repo, branch)
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
    user=Depends(get_verified_user),
    db: AsyncSession = Depends(get_async_session),
):
    await check_coder_permission(request, user)
    try:
        safe_path = validate_path(path)
    except ChangeSetValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail={'code': exc.code, 'message': exc.message})
    token = await _get_connection_token(user.id, db)
    try:
        file = await GitHubClient.get_file(token, owner, repo, safe_path, branch)
    except GitHubAPIError as exc:
        raise HTTPException(status_code=exc.status_code or status.HTTP_502_BAD_GATEWAY, detail={'code': exc.code, 'message': exc.message})
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
    token = await _get_connection_token(user.id, db)
    files = []
    errors = []
    for p in paths:
        try:
            safe_path = validate_path(str(p))
            file = await GitHubClient.get_file(token, owner, repo, safe_path, branch)
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
    token = await _get_connection_token(user.id, db)

    CODE_EXT = re.compile(r'\.(ts|tsx|js|jsx|mjs|cjs|py|go|rs|java|kt|scala|c|h|cpp|hpp|cs|rb|php|swift|lua|vue|svelte|sql|sh|bash|zsh|yaml|yml|json|toml|ini|cfg|md|txt|html|css|scss|less|xml|gradle|make|dockerfile)$', re.IGNORECASE)
    SKIP_DIR = re.compile(r'(^|/)(node_modules|\.git|dist|build|out|vendor|venv|__pycache__|\.next|coverage|target)/', re.IGNORECASE)

    try:
        tree_entries = await GitHubClient.get_tree(token, owner, repo, branch)
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
            safe_path = validate_path(path)
            file = await GitHubClient.get_file(token, owner, repo, safe_path, branch)
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
    try:
        normalized = validate_changeset(form.changeset.files, repo=f"{form.owner}/{form.repo}")
    except ChangeSetValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={'code': exc.code, 'message': exc.message, 'path': exc.path},
        )

    token = await _get_connection_token(user.id, db)
    diffs = []
    errors = []
    for entry in normalized['files']:
        old_content = None
        try:
            existing = await GitHubClient.get_file(token, form.owner, form.repo, entry['path'], form.base_branch)
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

    token = await _get_connection_token(user.id, db)

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
        await _run_export_job(job.id, token, form, normalized, user.id, db)
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


async def _run_export_job(job_id: str, token: str, form: CoderExportForm, normalized: dict, user_id: str, db: AsyncSession):
    await CoderExportJobs.update(job_id, {'status': 'running'}, db)

    owner, repo = form.owner, form.repo

    # Fail fast with a clear message if the OAuth token lacks write access to this repo
    # (otherwise GitHub returns an opaque 404/403 during ref creation).
    try:
        perms_response = await github_request(
            'GET', f'{GitHubClient.GITHUB_API_BASE}/repos/{quote(owner)}/{quote(repo)}', token=token
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

    base_sha = await GitHubClient.get_ref_commit_sha(token, owner, repo, form.base_branch)

    # create or reset working branch from base
    try:
        await GitHubClient.get_ref_commit_sha(token, owner, repo, form.branch)
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
            blob_sha = await GitHubClient.create_blob(token, owner, repo, entry['content'])
            entries.append({'path': entry['path'], 'mode': '100644', 'type': 'blob', 'sha': blob_sha})

    tree_sha = await GitHubClient.create_tree(token, owner, repo, base_sha, entries)
    commit_sha = await GitHubClient.create_commit(token, owner, repo, tree_sha, base_sha, form.commit_message)

    if branch_exists:
        await GitHubClient.update_ref(token, owner, repo, form.branch, commit_sha, force=False)
    else:
        await GitHubClient.create_ref(token, owner, repo, form.branch, commit_sha)

    pr = await GitHubClient.create_pull_request(
        token,
        owner,
        repo,
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
