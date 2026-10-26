"""Change Set validation & unified diff generation for Coder.

Rules (per technical specification):
- allowed actions: create | update | delete
- paths must be relative, normalized; no '..', no absolute paths, no '.git/' segments
- per-file and total size limits
- at most one operation per path
- diffs are generated server-side with difflib (unified format)
"""

import difflib
import fnmatch
import posixpath
import re

from open_webui.config import (
    CODER_BLOCKED_PATH_PATTERNS,
    CODER_ALLOWED_REPOS,
    CODER_MAX_FILE_SIZE,
    CODER_MAX_FILES_PER_CHANGESET,
    CODER_MAX_TOTAL_DIFF_SIZE,
)

ALLOWED_ACTIONS = {'create', 'update', 'delete', 'rename'}


class ChangeSetValidationError(Exception):
    def __init__(self, code: str, message: str, path: str | None = None):
        self.code = code
        self.message = message
        self.path = path
        super().__init__(message)


def _is_path_blocked(path: str) -> bool:
    """Проверяет, соответствует ли путь запрещенным шаблонам."""
    for pattern in CODER_BLOCKED_PATH_PATTERNS:
        if fnmatch.fnmatch(path, pattern):
            return True
    return False


def validate_path(path: str) -> str:
    """Normalize and validate a repository-relative path. Raises ChangeSetValidationError."""
    if not path or not isinstance(path, str):
        raise ChangeSetValidationError('CODER_INVALID_PATH', 'File path is required', path)
    stripped = path.strip()
    if stripped.startswith('/') or stripped.startswith('\\'):
        raise ChangeSetValidationError('CODER_INVALID_PATH', 'Absolute paths are not allowed', path)
    if len(stripped.encode()) > 1024:
        raise ChangeSetValidationError('CODER_INVALID_PATH', 'Path is too long', path)

    segments = stripped.replace('\\', '/').split('/')
    if any(seg == '..' for seg in segments):
        raise ChangeSetValidationError('CODER_INVALID_PATH', 'Path traversal is not allowed', path)
    normalized = posixpath.normpath(stripped.replace('\\', '/'))
    if normalized in ('.', '..', '') or normalized.startswith('../'):
        raise ChangeSetValidationError('CODER_INVALID_PATH', 'Path traversal is not allowed', path)
    if '.git' in segments:
        raise ChangeSetValidationError('CODER_INVALID_PATH', "'.git' paths are not allowed", path)
    # Проверка по запрещенным путям
    if _is_path_blocked(normalized):
        raise ChangeSetValidationError(
            'CODER_BLOCKED_PATH',
            f'Path "{normalized}" is blocked by policy',
            normalized,
        )
    return normalized


def validate_changeset(files: list[dict], repo: str | None = None) -> dict:
    """Validate a raw change set payload. Returns normalized change set.

    Raises ChangeSetValidationError on the first violation.
    """
    # Optionally validate allowed repos
    if repo and not is_repo_allowed(repo):
        raise ChangeSetValidationError(
            'CODER_DISALLOWED_REPO',
            f'Repository "{repo}" is not in the allowed list',
            None,
        )

    if not isinstance(files, list):
        raise ChangeSetValidationError('CODER_INVALID_CHANGESET', "'files' must be a list")
    if len(files) == 0:
        raise ChangeSetValidationError('CODER_EMPTY_CHANGESET', 'Change set is empty')
    if len(files) > CODER_MAX_FILES_PER_CHANGESET:
        raise ChangeSetValidationError(
            'CODER_TOO_MANY_FILES',
            f'Too many files: max {CODER_MAX_FILES_PER_CHANGESET} per change set',
        )

    seen_paths: set[str] = set()
    total_size = 0
    normalized_files = []

    for item in files:
        if not isinstance(item, dict):
            raise ChangeSetValidationError('CODER_INVALID_CHANGESET', 'Each file entry must be an object')

        action = (item.get('action') or '').strip().lower()
        if action not in ALLOWED_ACTIONS:
            raise ChangeSetValidationError(
                'CODER_INVALID_ACTION', f"Unknown action '{action}', expected create|update|delete|rename",
                item.get('path'),
            )

        path = validate_path(item.get('path', ''))
        if path in seen_paths:
            raise ChangeSetValidationError('CODER_DUPLICATE_PATH', f'Duplicate path in change set: {path}', path)
        seen_paths.add(path)

        content = item.get('content')
        if action == 'rename':
            old_path = item.get('old_path')
            if not old_path:
                raise ChangeSetValidationError(
                    'CODER_INVALID_ACTION', f"'old_path' is required for action 'rename'", path,
                )
            old_path = validate_path(old_path)
            if old_path in seen_paths:
                raise ChangeSetValidationError('CODER_DUPLICATE_PATH', f'Duplicate path in change set: {old_path}', old_path)
            seen_paths.add(old_path)
            # Content must be None for rename
            if content is not None:
                raise ChangeSetValidationError(
                    'CODER_INVALID_CONTENT', f"'content' must be None for action 'rename'", path,
                )
            normalized_files.append({'action': action, 'path': path, 'old_path': old_path, 'content': None})
        elif action in ('create', 'update'):
            if not isinstance(content, str):
                raise ChangeSetValidationError(
                    'CODER_INVALID_CONTENT', f"'content' is required for action '{action}'", path,
                )
            size = len(content.encode())
            if size > CODER_MAX_FILE_SIZE:
                raise ChangeSetValidationError(
                    'CODER_FILE_TOO_LARGE', f'File exceeds size limit ({CODER_MAX_FILE_SIZE} bytes)', path,
                )
            # Check for XSS patterns
            if re.search(r'<script', content, re.IGNORECASE):
                raise ChangeSetValidationError(
                    'CODER_INVALID_CONTENT', 'Potential XSS content detected', path
                )
            total_size += size
            normalized_files.append({'action': action, 'path': path, 'content': content})
        else:  # delete
            normalized_files.append({'action': action, 'path': path, 'content': None})

    if total_size > CODER_MAX_TOTAL_DIFF_SIZE:
        raise ChangeSetValidationError(
            'CODER_TOTAL_TOO_LARGE',
            f'Total change set size exceeds limit ({CODER_MAX_TOTAL_DIFF_SIZE} bytes)',
        )

    return {'files': normalized_files}


def generate_unified_diff(old_content: str | None, new_content: str | None, path: str) -> str:
    """Generate a unified diff between old and new content for display purposes."""
    from open_webui.config import CODER_MAX_DIFF_LINES

    old_lines = (old_content or '').splitlines(keepends=True)
    new_lines = (new_content or '').splitlines(keepends=True)
    diff_lines = list(
        difflib.unified_diff(old_lines, new_lines, fromfile=f'a/{path}', tofile=f'b/{path}', n=3)
    )
    if len(diff_lines) > CODER_MAX_DIFF_LINES:
        diff_lines = diff_lines[:CODER_MAX_DIFF_LINES]
        diff_lines.append(f'\n... diff truncated at {CODER_MAX_DIFF_LINES} lines ...\n')
    return ''.join(diff_lines)


def is_repo_allowed(repo: str) -> bool:
    """Check if the repository is in the allowed list from CODER_ALLOWED_REPOS.

    Supports glob-style patterns (e.g., 'org/*', 'my-repo').
    """
    if not CODER_ALLOWED_REPOS:
        return True
    for pattern in CODER_ALLOWED_REPOS:
        if fnmatch.fnmatch(repo, pattern):
            return True
    return False
