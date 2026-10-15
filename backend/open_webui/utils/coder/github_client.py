"""Async GitHub REST client for the Coder section (GitHub Cloud).

Implements the flows required by the technical specification:
- OAuth web flow token exchange & user info
- repository / branch listing, tree & file fetch
- export via Git Data API: blob -> tree -> commit -> ref update -> pull request
- error mapping to stable CODER_* codes; retry with backoff on 5xx/429
"""

import asyncio
import base64
import logging
import os
from urllib.parse import quote

import httpx

from open_webui.config import CODER_GITHUB_API_BASE_URL

log = logging.getLogger(__name__)

GITHUB_API = os.getenv('CODER_GITHUB_API_BASE_URL', CODER_GITHUB_API_BASE_URL) or 'https://api.github.com'
GITHUB_WEB = 'https://github.com'

MAX_RETRIES = 3
REQUEST_TIMEOUT = 30.0


class GitHubAPIError(Exception):
    """Maps GitHub errors to stable Coder error codes."""

    def __init__(self, code: str, message: str, status_code: int | None = None):
        self.code = code
        self.message = message
        self.status_code = status_code
        super().__init__(message)


def _headers(token: str) -> dict:
    return {
        'Authorization': f'Bearer {token}',
        'Accept': 'application/vnd.github+json',
        'X-GitHub-Api-Version': '2022-11-28',
        'User-Agent': 'open-webui-coder',
    }


async def _request(
    method: str,
    url: str,
    token: str | None = None,
    json_body: dict | None = None,
    params: dict | None = None,
) -> httpx.Response:
    headers = _headers(token) if token else {'Accept': 'application/vnd.github+json', 'User-Agent': 'open-webui-coder'}
    last_exc = None
    for attempt in range(MAX_RETRIES):
        try:
            async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
                response = await client.request(method, url, headers=headers, json=json_body, params=params)
            if response.status_code in (429, 500, 502, 503, 504):
                retry_after = response.headers.get('Retry-After')
                wait = float(retry_after) if retry_after and retry_after.isdigit() else (2**attempt)
                log.warning(f'GitHub API {method} {url} -> {response.status_code}, retrying in {wait}s')
                await asyncio.sleep(min(wait, 15))
                continue
            return response
        except httpx.HTTPError as exc:
            last_exc = exc
            await asyncio.sleep(2**attempt)
    raise GitHubAPIError('CODER_GITHUB_UNAVAILABLE', f'GitHub API is unreachable: {last_exc}')


def _raise_for_status(response: httpx.Response) -> None:
    status = response.status_code
    if 200 <= status < 300:
        return
    try:
        body = response.json()
        message = body.get('message', '')
        errors = body.get('errors') or []
        if errors and isinstance(errors, list):
            message = f"{message}: {errors[0].get('message', '')}" if message else errors[0].get('message', message)
    except Exception:
        message = response.text[:200]

    if status == 401:
        raise GitHubAPIError('CODER_GITHUB_UNAUTHORIZED', 'GitHub token is invalid or expired. Reconnect your account.', status)
    if status == 403:
        lowered = (message or '').lower()
        if 'rate limit' in lowered:
            raise GitHubAPIError('CODER_GITHUB_RATE_LIMIT', 'GitHub API rate limit exceeded. Try again later.', status)
        if 'protected branch' in lowered or 'not allowed to push' in lowered:
            raise GitHubAPIError('CODER_BRANCH_PROTECTED', f'Branch is protected: {message}', status)
        raise GitHubAPIError('CODER_FORBIDDEN', f'Access denied by GitHub: {message}', status)
    if status == 404:
        raise GitHubAPIError('CODER_NOT_FOUND', f'Not found on GitHub: {message}', status)
    if status == 409:
        raise GitHubAPIError('CODER_CONFLICT', f'Conflict: {message}', status)
    if status == 422:
        raise GitHubAPIError('CODER_VALIDATION_FAILED', f'GitHub validation failed: {message}', status)
    raise GitHubAPIError('CODER_GITHUB_ERROR', message or f'GitHub API error ({status})', status)


class GitHubClient:
    ####################
    # OAuth
    ####################

    @staticmethod
    async def exchange_code(code: str, state: str | None = None) -> dict:
        url = f'{GITHUB_WEB}/login/oauth/access_token'
        body = {
            'client_id': os.getenv('CODER_GITHUB_CLIENT_ID', CODER_GITHUB_CLIENT_ID_VALUE()),
            'client_secret': os.getenv('CODER_GITHUB_CLIENT_SECRET', CODER_GITHUB_CLIENT_SECRET_VALUE()),
            'code': code,
        }
        try:
            async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
                response = await client.post(url, json=body, headers={'Accept': 'application/json'})
        except httpx.HTTPError as exc:
            raise GitHubAPIError('CODER_GITHUB_UNAVAILABLE', f'Cannot reach GitHub OAuth endpoint: {exc}')
        if response.status_code != 200:
            raise GitHubAPIError('CODER_OAUTH_FAILED', 'GitHub OAuth token exchange failed', response.status_code)
        data = response.json()
        access_token = data.get('access_token')
        if not access_token:
            raise GitHubAPIError('CODER_OAUTH_FAILED', data.get('error_description', 'GitHub OAuth token exchange failed'))
        scopes = [s.strip() for s in (data.get('scope') or '').split(',') if s.strip()]
        return {'access_token': access_token, 'scope': scopes}

    @staticmethod
    async def get_user(token: str) -> dict:
        response = await _request('GET', f'{GITHUB_API}/user', token=token)
        _raise_for_status(response)
        data = response.json()
        return {'login': data.get('login'), 'id': str(data.get('id'))}

    @staticmethod
    async def validate_token(token: str) -> bool:
        try:
            await GitHubClient.get_user(token)
            return True
        except GitHubAPIError:
            return False

    ####################
    # Repositories / branches / tree / file
    ####################

    @staticmethod
    async def list_repositories(token: str, query: str | None = None, page: int = 1, per_page: int = 30) -> list[dict]:
        if query:
            url = f'{GITHUB_API}/search/repositories'
            params = {'q': query, 'per_page': per_page, 'page': page}
        else:
            url = f'{GITHUB_API}/user/repos'
            params = {'per_page': per_page, 'page': page, 'sort': 'updated'}
        response = await _request('GET', url, token=token, params=params)
        _raise_for_status(response)
        items = response.json()
        repos = items.get('items', items) if isinstance(items, dict) else items
        return [
            {
                'owner': repo['owner']['login'],
                'name': repo['name'],
                'full_name': repo['full_name'],
                'default_branch': repo.get('default_branch'),
                'private': repo.get('private', False),
                'push_allowed': bool(repo.get('permissions', {}).get('push')) if repo.get('permissions') else repo.get('pushed_at') is not None,
            }
            for repo in repos
        ]

    @staticmethod
    async def list_branches(token: str, owner: str, repo: str) -> list[dict]:
        response = await _request(
            'GET', f'{GITHUB_API}/repos/{quote(owner)}/{quote(repo)}/branches', token=token, params={'per_page': 100}
        )
        _raise_for_status(response)
        return [{'name': b['name'], 'sha': b['commit']['sha']} for b in response.json()]

    @staticmethod
    async def get_tree(token: str, owner: str, repo: str, branch: str) -> list[dict]:
        response = await _request(
            'GET',
            f'{GITHUB_API}/repos/{quote(owner)}/{quote(repo)}/git/trees/{quote(branch)}?recursive=1',
            token=token,
        )
        _raise_for_status(response)
        data = response.json()
        entries = [
            {'path': t['path'], 'type': t['type'], 'sha': t.get('sha')}
            for t in data.get('tree', [])
            if t['type'] in ('blob', 'tree')
        ]
        return entries

    @staticmethod
    async def get_file(token: str, owner: str, repo: str, path: str, ref: str) -> dict:
        response = await _request(
            'GET',
            f'{GITHUB_API}/repos/{quote(owner)}/{quote(repo)}/contents/{quote(path, safe="/")}',
            token=token,
            params={'ref': ref},
        )
        _raise_for_status(response)
        data = response.json()
        if isinstance(data, list):
            raise GitHubAPIError('CODER_NOT_A_FILE', 'Path refers to a directory')
        content_b64 = data.get('content') or ''
        try:
            content = base64.b64decode(content_b64).decode('utf-8')
        except (UnicodeDecodeError, ValueError):
            content = None
        return {
            'path': data.get('path'),
            'sha': data.get('sha'),
            'size': data.get('size'),
            'content': content,
            'binary': content is None,
        }

    ####################
    # Export: Git Data API flow
    ####################

    @staticmethod
    async def get_ref_commit_sha(token: str, owner: str, repo: str, branch: str) -> str:
        response = await _request(
            'GET', f'{GITHUB_API}/repos/{quote(owner)}/{quote(repo)}/git/ref/heads/{quote(branch)}', token=token
        )
        _raise_for_status(response)
        return response.json()['object']['sha']

    @staticmethod
    async def create_ref(token: str, owner: str, repo: str, branch: str, sha: str) -> None:
        response = await _request(
            'POST',
            f'{GITHUB_API}/repos/{quote(owner)}/{quote(repo)}/git/refs',
            token=token,
            json_body={'ref': f'refs/heads/{branch}', 'sha': sha},
        )
        if response.status_code == 422 and 'already exists' in response.text.lower():
            return  # branch already present
        _raise_for_status(response)

    @staticmethod
    async def update_ref(token: str, owner: str, repo: str, branch: str, sha: str, force: bool = False) -> None:
        response = await _request(
            'PATCH',
            f'{GITHUB_API}/repos/{quote(owner)}/{quote(repo)}/git/refs/heads/{quote(branch)}',
            token=token,
            json_body={'sha': sha, 'force': force},
        )
        _raise_for_status(response)

    @staticmethod
    async def create_blob(token: str, owner: str, repo: str, content: str) -> str:
        response = await _request(
            'POST',
            f'{GITHUB_API}/repos/{quote(owner)}/{quote(repo)}/git/blobs',
            token=token,
            json_body={'content': base64.b64encode(content.encode()).decode(), 'encoding': 'base64'},
        )
        _raise_for_status(response)
        return response.json()['sha']

    @staticmethod
    async def create_tree(token: str, owner: str, repo: str, base_sha: str, entries: list[dict]) -> str:
        response = await _request(
            'POST',
            f'{GITHUB_API}/repos/{quote(owner)}/{quote(repo)}/git/trees',
            token=token,
            json_body={'base_tree': base_sha, 'tree': entries},
        )
        _raise_for_status(response)
        return response.json()['sha']

    @staticmethod
    async def create_commit(token: str, owner: str, repo: str, tree_sha: str, parent_sha: str, message: str) -> str:
        response = await _request(
            'POST',
            f'{GITHUB_API}/repos/{quote(owner)}/{quote(repo)}/git/commits',
            token=token,
            json_body={'tree': tree_sha, 'parents': [parent_sha], 'message': message},
        )
        _raise_for_status(response)
        return response.json()['sha']

    @staticmethod
    async def create_pull_request(
        token: str, owner: str, repo: str, title: str, head: str, base: str, body: str | None = None
    ) -> dict:
        response = await _request(
            'POST',
            f'{GITHUB_API}/repos/{quote(owner)}/{quote(repo)}/pulls',
            token=token,
            json_body={'title': title, 'head': head, 'base': base, 'body': body or ''},
        )
        _raise_for_status(response)
        data = response.json()
        return {'html_url': data.get('html_url'), 'number': str(data.get('number'))}


def CODER_GITHUB_CLIENT_ID_VALUE() -> str:
    from open_webui.config import CODER_GITHUB_CLIENT_ID

    return CODER_GITHUB_CLIENT_ID


def CODER_GITHUB_CLIENT_SECRET_VALUE() -> str:
    from open_webui.config import CODER_GITHUB_CLIENT_SECRET

    return CODER_GITHUB_CLIENT_SECRET
