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
import time
from urllib.parse import quote

import httpx

from open_webui.config import CODER_GITHUB_API_BASE_URL, CODER_GITHUB_RETRY_DELAY, CODER_GITHUB_RETRY_MAX, CODER_GITHUB_RETRY_POLICY, CODER_GITHUB_TIMEOUT
from open_webui.utils.coder.metrics import observe_github_request

log = logging.getLogger(__name__)

GITHUB_API = os.getenv('CODER_GITHUB_API_BASE_URL', CODER_GITHUB_API_BASE_URL) or 'https://api.github.com'
GITHUB_WEB = 'https://github.com'

# Defaults; overridable at runtime through admin settings (coder.retry_* / coder.timeout)
MAX_RETRIES = CODER_GITHUB_RETRY_MAX
REQUEST_TIMEOUT = float(CODER_GITHUB_TIMEOUT)
RETRY_POLICY = CODER_GITHUB_RETRY_POLICY
RETRY_BASE_DELAY = float(CODER_GITHUB_RETRY_DELAY)


def get_retry_settings() -> dict:
    """Current retry/timeout settings (env defaults; router may override per request)."""
    return {
        'max_retries': MAX_RETRIES,
        'timeout': REQUEST_TIMEOUT,
        'policy': RETRY_POLICY,
        'base_delay': RETRY_BASE_DELAY,
    }


def _retry_wait(policy: str, base_delay: float, attempt: int) -> float:
    if policy == 'linear':
        return base_delay * (attempt + 1)
    if policy == 'constant':
        return base_delay
    # default: exponential backoff
    return max(base_delay, 2**attempt * base_delay)


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
    retry_settings: dict | None = None,
    accept: str | None = None,
) -> httpx.Response:
    """Perform a GitHub API request with configurable retry policy (§15.1).

    ``retry_settings`` may carry ``max_retries``, ``timeout``, ``policy``
    (exponential|linear|constant) and ``base_delay`` — resolved by the router
    from admin settings; env defaults otherwise.
    """
    settings = {**get_retry_settings(), **(retry_settings or {})}
    max_retries = int(settings['max_retries'])
    timeout = float(settings['timeout'])
    policy = str(settings['policy'])
    base_delay = float(settings['base_delay'])

    headers = _headers(token) if token else {'Accept': 'application/vnd.github+json', 'User-Agent': 'open-webui-coder'}
    if accept:
        headers['Accept'] = accept
    last_exc = None
    started = time.perf_counter()
    status_code = 0
    for attempt in range(max(1, max_retries)):
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.request(method, url, headers=headers, json=json_body, params=params)
            status_code = response.status_code
            if response.status_code in (429, 500, 502, 503, 504):
                observe_github_request(method, status_code, retried=True)
                retry_after = response.headers.get('Retry-After')
                if retry_after and retry_after.isdigit():
                    wait = float(retry_after)
                else:
                    wait = _retry_wait(policy, base_delay, attempt)
                log.warning(f'GitHub API {method} {url} -> {response.status_code}, retrying in {wait}s')
                await asyncio.sleep(min(wait, 15))
                continue
            observe_github_request(method, status_code)
            return response
        except httpx.HTTPError as exc:
            last_exc = exc
            observe_github_request(method, 0, error=type(exc).__name__)
            await asyncio.sleep(min(_retry_wait(policy, base_delay, attempt), 15))
    observe_github_request(method, status_code, error='retries_exhausted')
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


def _api_base(host: str | None) -> str:
    """§22.2 multi-GitHub: resolve API base URL for a connection host.

    github.com (and empty host) use the default API base; any other host is
    treated as a GitHub Enterprise Server domain with its /api/v3 endpoint.
    """
    if not host or host == 'github.com':
        return GITHUB_API
    h = host.strip().rstrip('/')
    if h.startswith('http://') or h.startswith('https://'):
        scheme, _, rest = h.partition('://')
    else:
        scheme, rest = 'https', h
    domain = rest.split('/')[0]
    if domain.endswith('/api/v3') or domain.endswith('/api/v4'):
        return f'{scheme}://{domain}'
    return f'{scheme}://{domain}/api/v3'


def _web_base(host: str | None) -> str:
    """Web base URL for a GHES host (OAuth authorize/token endpoints)."""
    h = (host or '').strip().rstrip('/')
    if not h or h == 'github.com':
        return GITHUB_WEB
    if not (h.startswith('http://') or h.startswith('https://')):
        h = f'https://{h}'
    return h


####################
# GitHub App authentication (plan coder.qwen.ai, priority D)
####################

_APP_TOKEN_CACHE: dict[str, tuple[str, float]] = {}  # installation_id -> (token, expires_at)


def github_app_configured(host: str | None = None) -> bool:
    from open_webui.config import CODER_GITHUB_APP_ID, CODER_GITHUB_APP_PRIVATE_KEY

    if host and host not in ('github.com', ''):
        # GHES App support is out of scope (docs/CODER.md §10.4): App ID/private key
        # below are single github.com credentials — do not claim them for other hosts.
        return False
    return bool(CODER_GITHUB_APP_ID and CODER_GITHUB_APP_PRIVATE_KEY)


def github_app_install_url(host: str | None = None) -> str | None:
    """Install URL for the configured GitHub App (settings → public link)."""
    from open_webui.config import CODER_GITHUB_APP_SLUG

    slug = CODER_GITHUB_APP_SLUG
    if not slug:
        return None
    web = _web_base(host)
    return f'{web}/apps/{slug}/installations/new'


def _app_jwt(host: str | None = None) -> str:
    """Signed JWT for GitHub App server-to-server auth (RS256, kid=App ID)."""
    import time as _time

    from open_webui.config import CODER_GITHUB_APP_ID, CODER_GITHUB_APP_PRIVATE_KEY

    try:
        import jwt  # PyJWT — optional dependency, required only when App is used
    except ImportError as exc:  # pragma: no cover
        raise GitHubAPIError('CODER_GITHUB_APP_UNSUPPORTED', f'PyJWT is not installed: {exc}')

    now = int(_time.time())
    payload = {'iat': now - 60, 'exp': now + 540, 'iss': str(CODER_GITHUB_APP_ID)}
    return jwt.encode(payload, CODER_GITHUB_APP_PRIVATE_KEY, algorithm='RS256')


async def get_installation_token(installation_id: str, host: str | None = None) -> str:
    """Exchange the App JWT for a short-lived installation token (cached ~TTL)."""
    cached = _APP_TOKEN_CACHE.get(installation_id)
    if cached and cached[1] > time.time() + 60:
        return cached[0]
    api_base = _api_base(host)
    jwt_token = _app_jwt(host)
    response = await _request(
        'POST',
        f"{api_base}/app/installations/{installation_id}/access_tokens",
        token=jwt_token,
    )
    _raise_for_status(response)
    data = response.json()
    token = data.get('token')
    if not token:
        raise GitHubAPIError('CODER_GITHUB_APP_ERROR', 'GitHub App returned no installation token')
    expires_in = 3600.0
    try:
        exp_str = (data.get('expires_at') or '')[:19]
        if exp_str:
            expires_in = max(60.0, min(3600.0, __import__('datetime').datetime.fromisoformat(exp_str).timestamp() - time.time()))
    except Exception:
        pass
    _APP_TOKEN_CACHE[installation_id] = (token, time.time() + expires_in)
    return token


async def list_user_installations(token: str, host: str | None = None) -> list[dict]:
    """GitHub App installations visible to the authenticated user."""
    api_base = _api_base(host)
    response = await _request('GET', f'{api_base}/user/installations', token=token, params={'per_page': 100})
    if response.status_code in (401, 403, 404):
        # App not installed / not visible — not an error for the caller
        return []
    _raise_for_status(response)
    items = response.json().get('installations') or []
    return [
        {
            'installation_id': str(i.get('id')),
            'account_login': (i.get('account') or {}).get('login'),
            'account_type': (i.get('account') or {}).get('type'),
            'repository_selection': i.get('repository_selection'),
        }
        for i in items
    ]


async def list_installation_repositories(installation_token: str, host: str | None = None) -> list[dict]:
    api_base = _api_base(host)
    repos: list[dict] = []
    page = 1
    while True:
        response = await _request(
            'GET',
            f'{api_base}/installation/repositories',
            token=installation_token,
            params={'per_page': 100, 'page': page},
        )
        _raise_for_status(response)
        data = response.json()
        batch = data.get('repositories') or []
        repos.extend(batch)
        if len(batch) < 100 or page >= (data.get('total_count', 0) // 100 + 1):
            break
        page += 1
    return [
        {
            'name': r.get('name'),
            'full_name': r.get('full_name'),
            'owner': (r.get('owner') or {}).get('login'),
            'default_branch': r.get('default_branch'),
            'private': r.get('private'),
            'updated_at': r.get('updated_at'),
        }
        for r in repos
    ]


class GitHubClient:
    GITHUB_API_BASE = GITHUB_API

    ####################
    # OAuth
    ####################

    @staticmethod
    async def exchange_code(code: str, state: str | None = None, host: str | None = None) -> dict:
        web_base = GITHUB_WEB if (not host or host == 'github.com') else _web_base(host)
        url = f'{web_base}/login/oauth/access_token'
        body = {
            'client_id': os.getenv('CODER_GITHUB_CLIENT_ID', CODER_GITHUB_CLIENT_ID_VALUE()),
            'client_secret': os.getenv('CODER_GITHUB_CLIENT_SECRET', CODER_GITHUB_CLIENT_SECRET_VALUE()),
            'code': code,
        }
        try:
            async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
                # GitHub's OAuth token endpoint accepts only application/x-www-form-urlencoded
                response = await client.post(
                    url,
                    data=body,
                    headers={'Accept': 'application/json', 'Content-Type': 'application/x-www-form-urlencoded'},
                )
        except httpx.HTTPError as exc:
            raise GitHubAPIError('CODER_GITHUB_UNAVAILABLE', f'Cannot reach GitHub OAuth endpoint: {exc}')
        if response.status_code != 200:
            try:
                detail = response.json().get('error_description') or response.json().get('error')
            except Exception:
                detail = response.text[:200]
            raise GitHubAPIError(
                'CODER_OAUTH_FAILED',
                f'GitHub OAuth token exchange failed ({response.status_code}): {detail}',
                response.status_code,
            )
        data = response.json()
        access_token = data.get('access_token')
        if not access_token:
            raise GitHubAPIError('CODER_OAUTH_FAILED', data.get('error_description', 'GitHub OAuth token exchange failed'))
        scopes = [s.strip() for s in (data.get('scope') or '').split(',') if s.strip()]
        return {'access_token': access_token, 'scope': scopes}

    @staticmethod
    async def get_user(token: str, host: str | None = None) -> dict:
        api_base = _api_base(host)
        response = await _request('GET', f'{api_base}/user', token=token)
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
    async def list_repositories(
        token: str,
        query: str | None = None,
        page: int = 1,
        per_page: int = 30,
        host: str | None = None,
        org: str | None = None,
    ) -> list[dict]:
        api_base = _api_base(host)
        # §D: filter the repository list by organization (org selector in the UI).
        if org:
            url = f'{api_base}/orgs/{quote(org)}/repos'
            params = {'per_page': per_page, 'page': page, 'type': 'all', 'sort': 'updated'}
            if query:
                params['q'] = query
        elif query:
            url = f'{api_base}/search/repositories'
            params = {'q': query, 'per_page': per_page, 'page': page}
        else:
            url = f'{api_base}/user/repos'
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
    async def list_branches(token: str, owner: str, repo: str, host: str | None = None) -> list[dict]:
        api_base = _api_base(host)
        response = await _request(
            'GET', f'{api_base}/repos/{quote(owner)}/{quote(repo)}/branches', token=token, params={'per_page': 100}
        )
        _raise_for_status(response)
        return [{'name': b['name'], 'sha': b['commit']['sha']} for b in response.json()]

    @staticmethod
    async def get_tree(token: str, owner: str, repo: str, branch: str, host: str | None = None) -> list[dict]:
        api_base = _api_base(host)
        response = await _request(
            'GET',
            f'{api_base}/repos/{quote(owner)}/{quote(repo)}/git/trees/{quote(branch)}?recursive=1',
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
    async def get_file(token: str, owner: str, repo: str, path: str, ref: str, host: str | None = None) -> dict:
        api_base = _api_base(host)
        response = await _request(
            'GET',
            f'{api_base}/repos/{quote(owner)}/{quote(repo)}/contents/{quote(path, safe="/")}',
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
    async def get_ref_commit_sha(token: str, owner: str, repo: str, branch: str, host: str | None = None) -> str:
        api_base = _api_base(host)
        response = await _request(
            'GET', f'{api_base}/repos/{quote(owner)}/{quote(repo)}/git/ref/heads/{quote(branch)}', token=token
        )
        _raise_for_status(response)
        return response.json()['object']['sha']

    @staticmethod
    async def create_ref(token: str, owner: str, repo: str, branch: str, sha: str, host: str | None = None) -> None:
        api_base = _api_base(host)
        response = await _request(
            'POST',
            f'{api_base}/repos/{quote(owner)}/{quote(repo)}/git/refs',
            token=token,
            json_body={'ref': f'refs/heads/{branch}', 'sha': sha},
        )
        if response.status_code == 422 and 'already exists' in response.text.lower():
            # Race/retry artifact: the ref appeared between our existence check and this
            # call. Reset it to the new commit instead of silently keeping the old one —
            # otherwise the PR would be opened from a stale branch (or fail with
            # "Not Found"/"No commits between base and head").
            await GitHubClient.update_ref(token, owner, repo, branch, sha, force=True)
            return
        _raise_for_status(response)

    @staticmethod
    async def update_ref(token: str, owner: str, repo: str, branch: str, sha: str, force: bool = False, host: str | None = None) -> None:
        api_base = _api_base(host)
        response = await _request(
            'PATCH',
            f'{api_base}/repos/{quote(owner)}/{quote(repo)}/git/refs/heads/{quote(branch)}',
            token=token,
            json_body={'sha': sha, 'force': force},
        )
        _raise_for_status(response)

    @staticmethod
    async def create_blob(token: str, owner: str, repo: str, content: str, host: str | None = None) -> str:
        api_base = _api_base(host)
        response = await _request(
            'POST',
            f'{api_base}/repos/{quote(owner)}/{quote(repo)}/git/blobs',
            token=token,
            json_body={'content': base64.b64encode(content.encode()).decode(), 'encoding': 'base64'},
        )
        _raise_for_status(response)
        return response.json()['sha']

    @staticmethod
    async def create_tree(token: str, owner: str, repo: str, base_sha: str, entries: list[dict], host: str | None = None) -> str:
        api_base = _api_base(host)
        response = await _request(
            'POST',
            f'{api_base}/repos/{quote(owner)}/{quote(repo)}/git/trees',
            token=token,
            json_body={'base_tree': base_sha, 'tree': entries},
        )
        _raise_for_status(response)
        return response.json()['sha']

    @staticmethod
    async def create_commit(token: str, owner: str, repo: str, tree_sha: str, parent_sha: str, message: str, host: str | None = None) -> str:
        api_base = _api_base(host)
        response = await _request(
            'POST',
            f'{api_base}/repos/{quote(owner)}/{quote(repo)}/git/commits',
            token=token,
            json_body={'tree': tree_sha, 'parents': [parent_sha], 'message': message},
        )
        _raise_for_status(response)
        return response.json()['sha']

    @staticmethod
    async def create_pull_request(
        token: str, owner: str, repo: str, title: str, head: str, base: str, body: str | None = None, host: str | None = None
    ) -> dict:
        api_base = _api_base(host)
        response = await _request(
            'POST',
            f'{api_base}/repos/{quote(owner)}/{quote(repo)}/pulls',
            token=token,
            json_body={'title': title, 'head': head, 'base': base, 'body': body or ''},
        )
        if response.status_code == 422 and 'already exists' in response.text.lower():
            # Idempotent re-export onto the same head/base: reuse the open PR rather than failing.
            pr = await GitHubClient.find_open_pull_request(token, owner, repo, head, base)
            if pr:
                return pr
        _raise_for_status(response)
        data = response.json()
        return {'html_url': data.get('html_url'), 'number': str(data.get('number'))}

    @staticmethod
    async def find_open_pull_request(token: str, owner: str, repo: str, head: str, base: str, host: str | None = None) -> dict | None:
        api_base = _api_base(host)
        """Return {html_url, number} of an open PR for head->base, or None."""
        response = await _request(
            'GET',
            f'{api_base}/repos/{quote(owner)}/{quote(repo)}/pulls',
            token=token,
            params={'state': 'open', 'head': f'{owner}:{head}', 'base': base, 'per_page': 5},
        )
        if response.status_code != 200:
            return None
        pulls = response.json()
        if not pulls:
            return None
        pr = pulls[0]
        return {'html_url': pr.get('html_url'), 'number': str(pr.get('number'))}

    # ---- Review comments (§22.2) ----

    @staticmethod
    async def get_pull_request_head_sha(token: str, owner: str, repo: str, pr_number: str, host: str | None = None) -> str | None:
        api_base = _api_base(host)
        response = await _request(
            'GET', f'{api_base}/repos/{quote(owner)}/{quote(repo)}/pulls/{quote(str(pr_number))}', token=token
        )
        if response.status_code != 200:
            return None
        return (response.json().get('head') or {}).get('sha')

    @staticmethod
    async def create_pull_request_review_comment(
        token: str, owner: str, repo: str, pr_number: str, commit_sha: str,
        path: str, line: int, body: str, side: str = 'RIGHT', host: str | None = None
    ) -> dict:
        api_base = _api_base(host)
        """Inline review comment on a PR diff line (REVIEW_COMMENTS event)."""
        response = await _request(
            'POST',
            f'{api_base}/repos/{quote(owner)}/{quote(repo)}/pulls/{quote(str(pr_number))}/comments',
            token=token,
            json_body={'commit_id': commit_sha, 'path': path, 'line': line, 'side': side, 'body': body},
        )
        _raise_for_status(response)
        data = response.json()
        return {'id': data.get('id'), 'html_url': data.get('html_url')}

    @staticmethod
    async def list_pull_request_review_comments(token: str, owner: str, repo: str, pr_number: str, host: str | None = None) -> list[dict]:
        api_base = _api_base(host)
        response = await _request(
            'GET',
            f'{api_base}/repos/{quote(owner)}/{quote(repo)}/pulls/{quote(str(pr_number))}/comments',
            token=token,
            params={'per_page': 100},
        )
        _raise_for_status(response)
        return [
            {
                'id': c.get('id'),
                'path': c.get('path'),
                'line': c.get('line'),
                'body': c.get('body'),
                'user': (c.get('user') or {}).get('login'),
                'created_at': c.get('created_at'),
                'html_url': c.get('html_url'),
            }
            for c in response.json()
        ]

    # ---- CI status (§22.2) ----

    @staticmethod
    async def get_commit_check_status(token: str, owner: str, repo: str, sha: str, host: str | None = None) -> dict:
        api_base = _api_base(host)
        """Combined check-runs + statuses for a commit (CI-статусы)."""
        combined = {'state': 'unknown', 'checks': [], 'statuses': []}
        run_resp = await _request(
            'GET',
            f'{api_base}/repos/{quote(owner)}/{quote(repo)}/commits/{quote(sha)}/check-runs',
            token=token,
            params={'per_page': 50},
            accept='application/vnd.github+json',
        )
        if run_resp.status_code == 200:
            for run in run_resp.json().get('check_runs', []):
                combined['checks'].append(
                    {
                        'name': run.get('name'),
                        'status': run.get('status'),
                        'conclusion': run.get('conclusion'),
                        'url': run.get('html_url') or run.get('details_url'),
                    }
                )
        status_resp = await _request(
            'GET', f'{api_base}/repos/{quote(owner)}/{quote(repo)}/commits/{quote(sha)}/status', token=token
        )
        if status_resp.status_code == 200:
            payload = status_resp.json()
            combined['state'] = payload.get('state') or combined['state']
            for st in (payload.get('statuses') or [])[:20]:
                combined['statuses'].append(
                    {'context': st.get('context'), 'state': st.get('state'), 'url': st.get('target_url')}
                )
        if combined['checks'] and not combined['statuses']:
            failing = [c for c in combined['checks'] if c['conclusion'] not in (None, 'success', 'skipped', 'neutral')]
            pending = [c for c in combined['checks'] if c['status'] != 'completed']
            combined['state'] = 'failure' if failing else ('pending' if pending else 'success')
        return combined

    # ---- Gist export (§22.2) ----

    @staticmethod
    async def create_gist(token: str, description: str, files: dict[str, str], public: bool = False, retry_settings: dict | None = None, host: str | None = None) -> dict:
        api_base = _api_base(host)
        response = await _request(
            'POST',
            f'{api_base}/gists',
            token=token,
            json_body={
                'description': description,
                'public': bool(public),
                'files': {name: {'content': content} for name, content in files.items()},
            },
            retry_settings=retry_settings,
        )
        _raise_for_status(response)
        data = response.json()
        return {'id': data.get('id'), 'html_url': data.get('html_url'), 'files': list((data.get('files') or {}).keys())}

    # ---- Auto-generated tests (§22.2) ----

    @staticmethod
    async def create_issue(token: str, owner: str, repo: str, title: str, body: str, labels: list[str] | None = None, retry_settings: dict | None = None, host: str | None = None) -> dict:
        api_base = _api_base(host)
        """Open an issue (used for auto-generated test backlog items)."""
        response = await _request(
            'POST',
            f'{api_base}/repos/{quote(owner)}/{quote(repo)}/issues',
            token=token,
            json_body={'title': title[:256], 'body': body, 'labels': labels or []},
            retry_settings=retry_settings,
        )
        _raise_for_status(response)
        data = response.json()
        return {'number': data.get('number'), 'html_url': data.get('html_url')}


def CODER_GITHUB_CLIENT_ID_VALUE() -> str:
    from open_webui.config import CODER_GITHUB_CLIENT_ID

    return CODER_GITHUB_CLIENT_ID


def CODER_GITHUB_CLIENT_SECRET_VALUE() -> str:
    from open_webui.config import CODER_GITHUB_CLIENT_SECRET

    return CODER_GITHUB_CLIENT_SECRET
