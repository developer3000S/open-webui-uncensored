"""Change Set validation & unified diff generation for Coder.

Rules (per technical specification):
- allowed actions: create | update | delete
- paths must be relative, normalized; no '..', no absolute paths, no '.git/' segments
- per-file and total size limits
- at most one operation per path
- diffs are generated server-side with difflib (unified format)
"""

import difflib
import posixpath

from open_webui.config import (
    CODER_MAX_FILE_SIZE,
    CODER_MAX_FILES_PER_CHANGESET,
    CODER_MAX_TOTAL_DIFF_SIZE,
)

ALLOWED_ACTIONS = {'create', 'update', 'delete'}


class ChangeSetValidationError(Exception):
    def __init__(self, code: str, message: str, path: str | None = None):
        self.code = code
        self.message = message
        self.path = path
        super().__init__(message)


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
    return normalized


def validate_changeset(files: list[dict]) -> dict:
    """Validate a raw change set payload. Returns normalized change set.

    Raises ChangeSetValidationError on the first violation.
    """
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
                'CODER_INVALID_ACTION', f"Unknown action '{action}', expected create|update|delete",
                item.get('path'),
            )

        path = validate_path(item.get('path', ''))
        if path in seen_paths:
            raise ChangeSetValidationError('CODER_DUPLICATE_PATH', f'Duplicate path in change set: {path}', path)
        seen_paths.add(path)

        content = item.get('content')
        if action in ('create', 'update'):
            if not isinstance(content, str):
                raise ChangeSetValidationError(
                    'CODER_INVALID_CONTENT', f"'content' is required for action '{action}'", path,
                )
            size = len(content.encode())
            if size > CODER_MAX_FILE_SIZE:
                raise ChangeSetValidationError(
                    'CODER_FILE_TOO_LARGE', f'File exceeds size limit ({CODER_MAX_FILE_SIZE} bytes)', path,
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
