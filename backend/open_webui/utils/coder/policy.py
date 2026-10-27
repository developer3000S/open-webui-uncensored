"""Admin-configurable policies for the Coder section (Этап 9, §15.1).

All policies resolve through the persistent ``Config`` layer (admin settings)
with environment-variable defaults from ``open_webui.config``. This allows an
administrator to change allowed GitHub hosts / orgs / repos, blocked paths,
mandatory-PR behaviour, retry policy and audit retention at runtime without
restarting the server.
"""

import fnmatch
import logging
from urllib.parse import urlparse

from open_webui.config import (
    CODER_ALLOWED_GITHUB_HOSTS,
    CODER_ALLOWED_ORGS,
    CODER_ALLOWED_REPOS,
    CODER_ASYNC_EXPORT,
    CODER_AUDIT_RETENTION_DAYS,
    CODER_BLOCKED_PATH_PATTERNS,
    CODER_GITHUB_RETRY_DELAY,
    CODER_GITHUB_RETRY_MAX,
    CODER_GITHUB_RETRY_POLICY,
    CODER_GITHUB_TIMEOUT,
    CODER_MAX_FILES_PER_CHANGESET,
    CODER_MAX_TOTAL_DIFF_SIZE,
    CODER_REQUIRE_PR,
)
from open_webui.models.config import Config

log = logging.getLogger(__name__)


async def _get(key: str, default):
    try:
        value = await Config.get(key, default)
    except Exception:  # pragma: no cover - defensive: DB unavailable
        log.debug('coder policy: Config.get(%s) failed, using default', key, exc_info=True)
        return default
    return default if value is None else value


def _as_list(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [v.strip() for v in value.split(',') if v.strip()]
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    return []


async def get_coder_policies() -> dict:
    """Resolve all coder.* admin settings into a single policy dict."""
    values = await Config.get_many(
        'coder.allowed_github_hosts',
        'coder.allowed_orgs',
        'coder.allowed_repos',
        'coder.blocked_paths',
        'coder.require_pr',
        'coder.max_files_per_changeset',
        'coder.max_total_diff_size',
        'coder.audit_retention_days',
        'coder.retry_policy',
        'coder.retry_max',
        'coder.retry_delay',
        'coder.timeout',
        'coder.async_export',
    )

    def pick(key, default):
        v = values.get(key)
        return default if v is None else v

    return {
        'allowed_github_hosts': [h.lower() for h in _as_list(pick('coder.allowed_github_hosts', CODER_ALLOWED_GITHUB_HOSTS))]
        or [h.lower() for h in CODER_ALLOWED_GITHUB_HOSTS],
        'allowed_orgs': _as_list(pick('coder.allowed_orgs', CODER_ALLOWED_ORGS)),
        'allowed_repos': _as_list(pick('coder.allowed_repos', CODER_ALLOWED_REPOS)),
        'blocked_paths': _as_list(pick('coder.blocked_paths', CODER_BLOCKED_PATH_PATTERNS)) or list(CODER_BLOCKED_PATH_PATTERNS),
        'require_pr': bool(pick('coder.require_pr', CODER_REQUIRE_PR)),
        'max_files_per_changeset': int(pick('coder.max_files_per_changeset', CODER_MAX_FILES_PER_CHANGESET)),
        'max_total_diff_size': int(pick('coder.max_total_diff_size', CODER_MAX_TOTAL_DIFF_SIZE)),
        'audit_retention_days': int(pick('coder.audit_retention_days', CODER_AUDIT_RETENTION_DAYS)),
        'retry_policy': str(pick('coder.retry_policy', CODER_GITHUB_RETRY_POLICY)),
        'retry_max': int(pick('coder.retry_max', CODER_GITHUB_RETRY_MAX)),
        'retry_delay': int(pick('coder.retry_delay', CODER_GITHUB_RETRY_DELAY)),
        'timeout': int(pick('coder.timeout', CODER_GITHUB_TIMEOUT)),
        'async_export': bool(pick('coder.async_export', CODER_ASYNC_EXPORT)),
    }


def host_is_allowed(url_or_host: str, allowed_hosts: list[str]) -> bool:
    """Validate that a GitHub API/web URL (or bare host) is on the allow-list."""
    if not allowed_hosts:
        return True
    host = url_or_host.lower()
    if '://' in host:
        host = urlparse(host).netloc.lower()
    host = host.split(':')[0]
    return any(fnmatch.fnmatch(host, pattern) for pattern in allowed_hosts)


def owner_is_allowed(owner: str, allowed_orgs: list[str]) -> bool:
    """Empty allow-list means unrestricted; otherwise glob-match the owner/org."""
    if not allowed_orgs:
        return True
    owner = (owner or '').lower()
    return any(fnmatch.fnmatch(owner, pattern.lower()) for pattern in allowed_orgs)


def repo_is_allowed(repo: str, allowed_repos: list[str]) -> bool:
    """`repo` is "owner/name"; empty allow-list means unrestricted."""
    if not allowed_repos:
        return True
    repo = (repo or '').lower()
    return any(fnmatch.fnmatch(repo, pattern.lower()) for pattern in allowed_repos)


def path_is_blocked(path: str, blocked_patterns: list[str]) -> bool:
    """Glob-match a repository-relative path against the block-list (§15.1)."""
    path = (path or '').lower()
    segments = path.split('/')
    for pattern in blocked_patterns:
        pattern = pattern.lower().strip()
        if not pattern:
            continue
        if fnmatch.fnmatch(path, pattern):
            return True
        # patterns like "secrets/*" should also match nested "secrets/a/b"
        if pattern.endswith('/*') and (path.startswith(pattern[:-2] + '/') or path == pattern[:-2]):
            return True
        # bare filename patterns (".env") match at any depth: ".env", "app/.env"
        if '/' not in pattern and '*' not in pattern:
            if segments[-1] == pattern or any(seg == pattern for seg in segments):
                return True
    return False
