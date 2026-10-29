"""Coder sandbox / preview / publish (план coder.qwen.ai, приоритет A).

MVP: изолированная файловая песочница на задачу в DATA_DIR/sandboxes/<session_id>.
Проект публикуется статикой: index.html инлайнит CSS/JS из папки публикации,
поэтому превью и публикация работают через один iframe-эндпоинт без dev-сервера.

Безопасность:
 - все пути канонизируются и проверяются на выход за пределы root (path traversal);
 - лимиты: кол-во файлов, размер файла, суммарный размер (CODER_SANDBOX_*);
 - запрещённые пути — CODER_BLOCKED_PATH_PATTERNS (.env, *.pem, secrets/* ...);
 - удаление только внутри собственного root (rmtree с pre-check).
"""

import fnmatch
import mimetypes
import os
import re
import shutil
from pathlib import Path

from open_webui.config import (
    CODER_BLOCKED_PATH_PATTERNS,
    CODER_MAX_TOTAL_DIFF_SIZE,
    CODER_SANDBOX_MAX_FILE_SIZE,
    CODER_SANDBOX_MAX_FILES,
    CODER_SANDBOX_MAX_TOTAL_SIZE,
    DATA_DIR,
)


class SandboxError(Exception):
    def __init__(self, code: str, message: str = None):
        self.code = code
        super().__init__(message or code)


def sandbox_root() -> Path:
    # env читается динамически: тесты могут переключать корни песочниц до/после импорта config
    root_env = os.getenv('CODER_SANDBOX_ROOT', '')
    root = Path(root_env) if root_env else Path(DATA_DIR) / 'sandboxes'
    root.mkdir(parents=True, exist_ok=True)
    return root


def publish_root() -> Path:
    root_env = os.getenv('CODER_PUBLISH_ROOT', '')
    root = Path(root_env) if root_env else Path(DATA_DIR) / 'published'
    root.mkdir(parents=True, exist_ok=True)
    return root


SAFE_SESSION_ID = re.compile(r'^[0-9a-fA-F-]{8,64}$')


def _validate_session_id(session_id: str) -> str:
    if not session_id or not SAFE_SESSION_ID.match(session_id):
        raise SandboxError('invalid_session_id')
    return session_id


def _validate_rel_path(path: str) -> str:
    """Нормализует относительный путь; отклоняет абсолютные/выходящие за root."""
    if not path or path.startswith('/') or '\\x00' in path:
        raise SandboxError('invalid_path', f'invalid path: {path!r}')
    parts = []
    for part in path.replace('\\', '/').split('/'):
        if part in ('', '.'):
            continue
        if part == '..':
            raise SandboxError('invalid_path', f'path escapes root: {path!r}')
        parts.append(part)
    if not parts:
        raise SandboxError('invalid_path', 'empty path')
    rel = '/'.join(parts)
    for pattern in CODER_BLOCKED_PATH_PATTERNS:
        if fnmatch.fnmatch(rel, pattern) or fnmatch.fnmatch(os.path.basename(rel), pattern):
            raise SandboxError('blocked_path', f'path matches blocked pattern: {pattern}')
    return rel


def _resolve(root: Path, rel: str) -> Path:
    target = (root / rel).resolve()
    root_r = root.resolve()
    if not str(target).startswith(str(root_r) + os.sep) and target != root_r:
        raise SandboxError('invalid_path', f'path escapes root: {rel!r}')
    return target


def sandbox_dir(session_id: str) -> Path:
    _validate_session_id(session_id)
    return sandbox_root() / session_id


def create_sandbox(session_id: str, skeleton: dict | None = None) -> Path:
    """Создаёт папку sandbox и опционально кладёт стартовый скелет (§B1/B2)."""
    d = sandbox_dir(session_id)
    d.mkdir(parents=True, exist_ok=False)
    for rel, content in (skeleton or {}).items():
        write_file(session_id, rel, content)
    return d


def list_files(session_id: str) -> list[dict]:
    d = sandbox_dir(session_id)
    if not d.is_dir():
        raise SandboxError('not_found', 'sandbox session directory missing')
    out = []
    for p in sorted(d.rglob('*')):
        if p.is_file():
            rel = str(p.relative_to(d)).replace(os.sep, '/')
            stat = p.stat()
            out.append({'path': rel, 'size': stat.st_size, 'mtime': int(stat.st_mtime)})
    return out


def read_file(session_id: str, path: str) -> tuple[str, str]:
    """Возвращает (content, mime) для текстовых файлов; бинарные — base64 не поддерживается MVP."""
    d = sandbox_dir(session_id)
    rel = _validate_rel_path(path)
    target = _resolve(d, rel)
    if not target.is_file():
        raise SandboxError('not_found', f'file not found: {rel}')
    if target.stat().st_size > CODER_SANDBOX_MAX_FILE_SIZE:
        raise SandboxError('too_large', f'file exceeds {CODER_SANDBOX_MAX_FILE_SIZE} bytes')
    try:
        content = target.read_text(encoding='utf-8')
    except UnicodeDecodeError:
        raise SandboxError('binary_file', f'binary file not supported by MVP: {rel}')
    mime = mimetypes.guess_type(rel)[0] or 'text/plain'
    return content, mime


def write_file(session_id: str, path: str, content: str) -> dict:
    d = sandbox_dir(session_id)
    if not d.is_dir():
        raise SandboxError('not_found', 'sandbox session directory missing')
    rel = _validate_rel_path(path)
    data = content.encode('utf-8')
    if len(data) > CODER_SANDBOX_MAX_FILE_SIZE:
        raise SandboxError('too_large', f'file exceeds {CODER_SANDBOX_MAX_FILE_SIZE} bytes')
    files = list_files(session_id)
    existing = {f['path']: f for f in files}
    total = sum(f['size'] for f in files) - existing.get(rel, {}).get('size', 0) + len(data)
    if total > CODER_SANDBOX_MAX_TOTAL_SIZE:
        raise SandboxError('quota_exceeded', 'sandbox total size limit exceeded')
    if rel not in existing and len(files) >= CODER_SANDBOX_MAX_FILES:
        raise SandboxError('quota_exceeded', f'sandbox file count limit ({CODER_SANDBOX_MAX_FILES}) exceeded')
    target = _resolve(d, rel)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    return {'path': rel, 'size': len(data)}


def delete_file(session_id: str, path: str) -> bool:
    d = sandbox_dir(session_id)
    rel = _validate_rel_path(path)
    target = _resolve(d, rel)
    if target.is_file():
        target.unlink()
        return True
    return False


def destroy_sandbox(session_id: str) -> bool:
    """Полное удаление sandbox-директории (жизненный цикл destroy §A1)."""
    d = sandbox_dir(session_id)
    root_r = sandbox_root().resolve()
    resolved = d.resolve()
    if str(resolved).startswith(str(root_r) + os.sep) and resolved.is_dir():
        shutil.rmtree(resolved)
        return True
    return False


def apply_changeset(session_id: str, files: list[dict]) -> list[dict]:
    """§A5 Stop/rollback-friendly применение change set к sandbox.

    elements: {action: create|update|delete, path, content}
    """
    applied = []
    for item in files:
        action = item.get('action', 'update')
        path = item.get('path', '')
        if action == 'delete':
            ok = delete_file(session_id, path)
            applied.append({'path': path, 'action': action, 'ok': ok})
        else:
            info = write_file(session_id, path, item.get('content') or '')
            applied.append({'path': info['path'], 'action': 'write', 'size': info['size']})
    return applied


def build_single_file_html(src_dir: Path) -> str:
    """Собирает index.html со встроенными css/js — для iframe-превью и публикации."""
    index_path = src_dir / 'index.html'
    if index_path.is_file():
        html = index_path.read_text(encoding='utf-8', errors='replace')
    else:
        html = '<!doctype html>\n<html><head><meta charset="utf-8"><title>Sandbox</title></head><body></body></html>'

    def _inline_css(match):
        href = match.group(1)
        try:
            rel = _validate_rel_path(href)
            p = (src_dir / rel).resolve()
            if str(p).startswith(str(src_dir.resolve())) and p.is_file():
                return f'<style>\n{p.read_text(encoding="utf-8", errors="replace")}\n</style>'
        except Exception:
            pass
        return match.group(0)

    def _inline_js(match):
        src = match.group(1)
        try:
            rel = _validate_rel_path(src)
            p = (src_dir / rel).resolve()
            if str(p).startswith(str(src_dir.resolve())) and p.is_file():
                code = p.read_text(encoding='utf-8', errors='replace').replace('</script>', '<\\/script>')
                return f'<script>\n{code}\n</script>'
        except Exception:
            pass
        return match.group(0)

    html = re.sub(r'<link[^>]+href=["\']([^"\']+\.css)["\'][^>]*>', _inline_css, html)
    html = re.sub(r'<script[^>]+src=["\']([^"\']+\.js)["\'][^>]*>', _inline_js, html)
    return html


def get_preview_html(session_id: str) -> str:
    """HTML живой превью-панели (§A2): index.html sandbox со inlined ассетами."""
    d = sandbox_dir(session_id)
    if not d.is_dir():
        raise SandboxError('not_found', 'sandbox session directory missing')
    return build_single_file_html(d)


def publish_sandbox(session_id: str, share_id: str) -> dict:
    """§A4 публикация одним кликом: копия собранного проекта в published/<share_id>."""
    _validate_session_id(share_id)
    src = sandbox_dir(session_id)
    if not src.is_dir():
        raise SandboxError('not_found', 'sandbox session directory missing')
    dst = publish_root() / share_id
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst)
    # Собираем единый index.html поверх копии для простого хостинга
    (dst / 'index.html').write_text(build_single_file_html(dst), encoding='utf-8')
    size = sum(f.stat().st_size for f in dst.rglob('*') if f.is_file())
    if size > CODER_MAX_TOTAL_DIFF_SIZE * 4:
        raise SandboxError('quota_exceeded', 'published project too large')
    return {'share_id': share_id, 'files': len([f for f in dst.rglob('*') if f.is_file()]), 'size': size}


def read_published(share_id: str) -> str:
    _validate_session_id(share_id)
    p = (publish_root() / share_id / 'index.html').resolve()
    root_r = publish_root().resolve()
    if not str(p).startswith(str(root_r) + os.sep) or not p.is_file():
        raise SandboxError('not_found', 'published page not found')
    return p.read_text(encoding='utf-8', errors='replace')


def export_zip(session_id: str) -> bytes:
    """§C-im/export: собрать песочницу в zip-архив (без GitHub).

    В архив кладутся все текстовые файлы сессии (как в copy_sandbox) и
    манифест coder-sandbox.json с метаданными для последующего импорта.
    """
    import io
    import json
    import zipfile

    _validate_session_id(session_id)
    src = sandbox_dir(session_id)
    if not src.is_dir():
        raise SandboxError('not_found', 'sandbox session directory missing')

    manifest = {
        'coder_sandbox': 1,
        'session_id': session_id,
        'exported_at': int(__import__('time').time()),
        'files': [],
    }
    buf = io.BytesIO()
    total = 0
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
        for f in list_files(session_id):
            rel = f['path']
            try:
                content, _mime = read_file(session_id, rel)
            except SandboxError:
                continue
            data = content.encode('utf-8')
            total += len(data)
            if total > CODER_SANDBOX_MAX_TOTAL_SIZE:
                raise SandboxError('too_large', 'sandbox exceeds export size limit')
            zf.writestr(f'files/{rel}', data)
            manifest['files'].append({'path': rel, 'size': len(data)})
        zf.writestr('coder-sandbox.json', json.dumps(manifest, ensure_ascii=False, indent=2))
    return buf.getvalue()


def import_zip_bytes(archive: bytes) -> dict:
    """§C-im/export: разобрать zip из export_zip().

    Возвращает {'manifest': ..., 'files': {rel_path: content}}; валидирует
    пути через _validate_rel_path (path traversal), объём — через лимиты
    песочницы. Бросает SandboxError при недопустимом архиве.
    """
    import io
    import json
    import zipfile

    try:
        zf = zipfile.ZipFile(io.BytesIO(archive))
    except zipfile.BadZipFile:
        raise SandboxError('bad_zip', 'uploaded file is not a valid zip archive')
    try:
        manifest_raw = zf.read('coder-sandbox.json')
    except KeyError:
        raise SandboxError('no_manifest', 'zip is not a Coder sandbox export (coder-sandbox.json missing)')
    try:
        manifest = json.loads(manifest_raw.decode('utf-8'))
    except (ValueError, UnicodeDecodeError):
        raise SandboxError('bad_manifest', 'coder-sandbox.json is corrupt')
    if not isinstance(manifest, dict) or manifest.get('coder_sandbox') != 1:
        raise SandboxError('bad_manifest', 'unexpected coder-sandbox.json structure')

    files: dict[str, str] = {}
    total = 0
    prefix = 'files/'
    for name in zf.namelist():
        if not name.startswith(prefix) or name.endswith('/'):
            continue
        rel = name[len(prefix):]
        try:
            rel = _validate_rel_path(rel)
        except SandboxError:
            continue  # пропускаем опасные/битые пути вместо отказа всего импорта
        data = zf.read(name)
        if len(data) > CODER_SANDBOX_MAX_FILE_SIZE:
            continue  # слишком большие файлы пропускаем (квота на файл)
        total += len(data)
        if total > CODER_SANDBOX_MAX_TOTAL_SIZE:
            raise SandboxError('too_large', 'import exceeds sandbox size limit')
        try:
            files[rel] = data.decode('utf-8')
        except UnicodeDecodeError:
            continue  # бинарные файлы не поддерживаются форматом экспорта
    if not files and manifest.get('files'):
        raise SandboxError('empty_archive', 'manifest lists files but the archive contains none')
    return {'manifest': manifest, 'files': files}


def copy_sandbox(src_session_id: str, dst_session_id: str) -> dict:
    """§C4 fork: копия файлов песочницы одной сессии в другую (для fork-задач).

    Копируются только текстовые файлы в пределах лимитов получателя; исходник
    не изменяется. Возвращает {'copied': [...], 'skipped': [...]}.
    """
    src = sandbox_dir(src_session_id)
    if not src.is_dir():
        raise SandboxError('not_found', 'source sandbox session directory missing')
    dst = sandbox_dir(dst_session_id)
    if not dst.is_dir():
        raise SandboxError('not_found', 'destination sandbox session directory missing')
    copied, skipped = [], []
    for f in list_files(src_session_id):
        rel = f['path']
        try:
            content, _mime = read_file(src_session_id, rel)
            info = write_file(dst_session_id, rel, content)
            copied.append({'path': rel, 'size': info['size']})
        except SandboxError as exc:
            skipped.append({'path': rel, 'reason': exc.code})
    return {'copied': copied, 'skipped': skipped}
