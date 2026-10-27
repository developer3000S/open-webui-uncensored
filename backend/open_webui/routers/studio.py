"""
studio.py — мост между Uncensored Local Studio (стек llama.cpp / stable-diffusion.cpp /
whisper.cpp / Kokoro TTS) и Open WebUI.

Маршрут подключается с префиксом ``/api/v1/studio`` и пробрасывает запросы к локальным
движкам студии, которые запускаются лаунчером ``studio/scripts/server/serve.cjs``:

    * LLM-движок            — ``llama-server``  (OpenAI-совместимый API, порт ``STUDIO_LLM_PORT``, по умолчанию 10086)
    * SD-движок             — ``sd-server``     (stable-diffusion.cpp REST, порт ``STUDIO_SD_PORT``, по умолчанию 8080)
    * Whisper-движок        — ``whisper-cli``   (управляется через HTTP API студии, порт ``STUDIO_API_PORT``, по умолчанию 14200)
    * Kokoro TTS-движок     — ``kokoro-js``     (управляется через HTTP API студии, порт ``STUDIO_API_PORT``)

Дополнительно модуль умеет сам spawn-ить (запускать) ``llama-server`` из бинарников, установленных
скриптами ``studio/scripts/setup/*``, если внешний процесс не запущен
(``STUDIO_AUTO_START_LLM=true``).

Все ответы нормализуются в единый формат Open WebUI, чтобы движки студии можно было
использовать как обычные модели чата, генерации изображений и аудио прямо из интерфейса
Open WebUI (через ``openai.api_base_urls`` / ``images.api_base_urls`` / ``audio.*``).
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

import aiohttp
from fastapi import APIRouter, Body, File, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse, StreamingResponse

log = logging.getLogger(__name__)

router = APIRouter()

# ── Конфигурация портов движков (переопределяется через .env) ────────────────────────
STUDIO_ROOT = Path(os.environ.get('STUDIO_ROOT', str(Path(__file__).resolve().parents[3] / 'studio')))

STUDIO_API_PORT = int(os.environ.get('STUDIO_API_PORT', os.environ.get('FRONTEND_PORT', '14200')))
STUDIO_LLM_PORT = int(os.environ.get('STUDIO_LLM_PORT', os.environ.get('TEXT_API', '10086')))
STUDIO_SD_PORT = int(os.environ.get('STUDIO_SD_PORT', os.environ.get('API_GPU', '8080')))
STUDIO_SPEECH_PORT = int(os.environ.get('STUDIO_SPEECH_PORT', '10088'))
STUDIO_TTS_PORT = int(os.environ.get('STUDIO_TTS_PORT', '10089'))
STUDIO_AUTO_START_LLM = os.environ.get('STUDIO_AUTO_START_LLM', 'false').lower() == 'true'

STUDIO_BASE = f'http://127.0.0.1:{STUDIO_API_PORT}'
LLM_BASE = f'http://127.0.0.1:{STUDIO_LLM_PORT}/v1'
SD_BASE = f'http://127.0.0.1:{STUDIO_SD_PORT}'

REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=None, sock_connect=15, sock_read=600)

_llm_process: subprocess.Popen | None = None


def _backend_available(base_url: str) -> bool:
    """Быстрая проверка живости движка (GET /v1/models или /sd-info)."""
    try:
        import urllib.request

        with urllib.request.urlopen(base_url.rstrip('/') + '/models', timeout=2):
            return True
    except Exception:
        return False


# ── Менеджеры процессов (fallback: самостоятельный запуск бинарников студии) ─────────


def _find_llama_server_binary() -> str | None:
    candidates = [
        STUDIO_ROOT / 'app' / 'llm-backend' / 'linux' / 'cuda' / 'llama-server',
        STUDIO_ROOT / 'app' / 'llm-backend' / 'linux' / 'vulkan' / 'llama-server',
        STUDIO_ROOT / 'app' / 'llm-backend' / 'linux' / 'cpu' / 'llama-server',
        STUDIO_ROOT / 'app' / 'llm-backend' / 'mac' / 'arm64' / 'llama-server',
        STUDIO_ROOT / 'app' / 'llm-backend' / 'mac' / 'x64' / 'llama-server',
        STUDIO_ROOT / 'app' / 'llm-backend' / 'win' / 'cuda' / 'llama-server.exe',
        STUDIO_ROOT / 'app' / 'llm-backend' / 'win' / 'vulkan' / 'llama-server.exe',
        STUDIO_ROOT / 'app' / 'llm-backend' / 'win' / 'cpu' / 'llama-server.exe',
    ]
    for c in candidates:
        if c.exists():
            return str(c)
    return shutil.which('llama-server')


def ensure_llama_server(model_path: str | None = None) -> dict:
    """Возвращает статус LLM-движка; при ``STUDIO_AUTO_START_LLM`` поднимает llama-server сам."""
    global _llm_process
    status = {
        'running': _backend_available(LLM_BASE),
        'managed_by_studio_launcher': _backend_available(STUDIO_BASE),
        'auto_start': STUDIO_AUTO_START_LLM,
        'binary': _find_llama_server_binary(),
        'port': STUDIO_LLM_PORT,
    }
    if status['running'] or not STUDIO_AUTO_START_LLM:
        return status

    binary = status['binary']
    if not binary:
        raise HTTPException(
            status_code=503,
            detail='llama-server не найден. Запустите лаунчер студии (linux.sh / windows.bat / mac.sh) '
            'или установите бэкенды через studio/scripts/setup.',
        )

    gguf_dir = STUDIO_ROOT / 'app' / 'llm-models'
    if model_path is None and gguf_dir.exists():
        models = sorted(gguf_dir.glob('*.gguf'), key=lambda p: p.stat().st_mtime, reverse=True)
        if models:
            model_path = str(models[0])
    if not model_path:
        raise HTTPException(status_code=400, detail='Не указана GGUF-модель для автозапуска llama-server.')

    cmd = [binary, '--model', model_path, '--port', str(STUDIO_LLM_PORT), '--host', '127.0.0.1']
    log.info(f'studio: автозапуск llama-server: {" ".join(cmd)}')
    _llm_process = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    # Ждём готовности до 120 секунд (загрузка больших моделей медленная)
    deadline = time.time() + 120
    while time.time() < deadline:
        if _backend_available(LLM_BASE):
            status['running'] = True
            break
        time.sleep(2)
    return status


# ── Статус всех движков ──────────────────────────────────────────────────────────────


@router.get('/status')
async def studio_status():
    """Сводка по всем четырём движкам студии (LLM / SD / Whisper / Kokoro TTS)."""

    async def probe(url: str) -> bool:
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=3)) as s:
                async with s.get(url) as r:
                    return r.status < 500
        except Exception:
            return False

    llm_ok = await probe(f'{LLM_BASE}/models')
    sd_ok = await probe(SD_BASE)
    api_ok = await probe(f'{STUDIO_BASE}/api/telemetry')
    return {
        'studio_root': str(STUDIO_ROOT),
        'engines': {
            'llm': {'running': llm_ok, 'base_url': LLM_BASE, 'port': STUDIO_LLM_PORT},
            'image_generation': {'running': sd_ok, 'base_url': SD_BASE, 'port': STUDIO_SD_PORT},
            'speech_to_text': {
                'running': api_ok,
                'control_api': f'{STUDIO_BASE}/api/speech',
                'port': STUDIO_SPEECH_PORT,
            },
            'text_to_speech': {'running': api_ok, 'control_api': f'{STUDIO_BASE}/api/tts', 'port': STUDIO_TTS_PORT},
        },
        'launcher_api_online': api_ok,
        'webui_integration': {
            'openai_api_base_url': LLM_BASE,
            'images_api_base_url': SD_BASE,
            'compatible_endpoints': [
                'POST /api/v1/studio/chat/completions',
                'POST /api/v1/studio/images/generations',
                'POST /api/v1/studio/audio/transcriptions',
                'POST /api/v1/studio/audio/speech',
                'GET  /api/v1/studio/models',
            ],
        },
    }


@router.get('/models')
async def studio_models():
    """Список моделей из движков студии (GGUF-чат + safetensors-изображения)."""
    result: dict[str, Any] = {'chat': [], 'image': []}
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=5)) as s:
        try:
            async with s.get(f'{LLM_BASE}/models') as r:
                if r.status == 200:
                    data = await r.json()
                    result['chat'] = [m.get('id') for m in data.get('data', [])]
        except Exception as e:
            log.debug(f'studio llm models unavailable: {e}')
        try:
            gguf_dir = STUDIO_ROOT / 'app' / 'llm-models'
            if gguf_dir.exists():
                result['chat_files'] = [p.name for p in gguf_dir.glob('*.gguf')]
        except Exception:
            pass
        try:
            sd_dir = STUDIO_ROOT / 'app' / 'models'
            if sd_dir.exists():
                result['image'] = [p.name for p in list(sd_dir.glob('*.safetensors')) + list(sd_dir.glob('*.ckpt'))]
        except Exception:
            pass
    return result


# ── Чат (проксирование на llama-server студии) ───────────────────────────────────────


@router.post('/chat/completions')
async def studio_chat_completions(request: Request):
    """OpenAI-совместимый чат через llama-движок студии. Поддерживает stream=true."""
    body = await request.json()
    if not _backend_available(LLM_BASE):
        try:
            ensure_llama_server(body.pop('_model_path', None))
        except HTTPException:
            raise
        if not _backend_available(LLM_BASE):
            raise HTTPException(
                status_code=503,
                detail='LLM-движок студии не запущен. Откройте рабочее место чата в Uncensored AI Studio.',
            )

    payload = {k: v for k, v in body.items() if not k.startswith('_')}
    stream = bool(payload.get('stream'))

    async with aiohttp.ClientSession(timeout=REQUEST_TIMEOUT) as session:
        async with session.post(f'{LLM_BASE}/chat/completions', json=payload) as upstream:
            if upstream.status != 200:
                text_body = await upstream.text()
                raise HTTPException(status_code=upstream.status, detail=text_body)
            if not stream:
                return JSONResponse(await upstream.json())

            async def event_stream():
                async for chunk in upstream.content.iter_any():
                    yield chunk

            return StreamingResponse(
                event_stream(),
                media_type='text/event-stream',
                headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'},
            )


# ── Генерация изображений (stable-diffusion.cpp) ─────────────────────────────────────


@router.post('/images/generations')
async def studio_images_generations(payload: dict = Body(...)):
    """Генерация изображения движком stable-diffusion.cpp студии.

    Принимает OpenAI-DALL-E-подобный запрос ``{prompt, negative_prompt?, size?, steps?, cfg_scale?, seed?, model?}``
    и возвращает base64 в формате ``{created, data:[{b64_json}]}``.
    """
    if not _backend_available(SD_BASE.replace(':8080', '')) and not await _probe_sd():
        raise HTTPException(
            status_code=503,
            detail='SD-движок студии не запущен. Переключитесь на рабочее место генерации изображений в Uncensored AI Studio.',
        )

    width, height = 512, 512
    size = payload.get('size')
    if isinstance(size, str) and 'x' in size.lower():
        try:
            w, h = size.lower().split('x', 1)
            width, height = int(w), int(h)
        except ValueError:
            pass

    sd_body = {
        'prompt': payload.get('prompt', ''),
        'width': width,
        'height': height,
        'sample_method': payload.get('sample_method', 'euler_a'),
        'sample_steps': int(payload.get('steps', payload.get('sample_steps', 20))),
        'cfg_scale': float(payload.get('cfg_scale', 7.0)),
        'seed': int(payload.get('seed', -1)),
    }
    if payload.get('negative_prompt'):
        sd_body['negative_prompt'] = payload['negative_prompt']
    if payload.get('model_path'):
        sd_body['model_path'] = payload['model_path']

    async with aiohttp.ClientSession(timeout=REQUEST_TIMEOUT) as session:
        # стабильный эндпоинт stable-diffusion.cpp в студии — OpenAI-подобный /v1/images/generations
        last_error = None
        data = None
        for endpoint in (f'{SD_BASE}/v1/images/generations', f'{SD_BASE}/sdgen'):
            try:
                async with session.post(endpoint, json={**sd_body, 'n': 1, 'response_format': 'b64_json'}) as upstream:
                    if upstream.status != 200:
                        last_error = f'{endpoint} -> {upstream.status}: {(await upstream.text())[:300]}'
                        continue
                    data = await upstream.json()
                    break
            except aiohttp.ClientError as e:
                last_error = str(e)
        if data is None:
            raise HTTPException(status_code=502, detail=f'SD-движок вернул ошибку: {last_error}')

    images = []
    entries = data.get('data') if isinstance(data.get('data'), list) else []
    for item in entries:
        b64 = item.get('b64_json') or ''
        if b64:
            images.append({'b64_json': b64.split(',', 1)[-1] if b64.startswith('data:') else b64})
    if not images:
        b64 = data.get('b64_json') or data.get('image') or ''
        if b64:
            images.append({'b64_json': b64.split(',', 1)[-1] if str(b64).startswith('data:') else b64})
    return {'created': int(time.time()), 'data': images, 'raw': {k: v for k, v in data.items() if k != 'data'}}


async def _probe_sd() -> bool:
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=3)) as s:
            async with s.get(SD_BASE) as r:
                return r.status < 500
    except Exception:
        return False


# ── Аудио: распознавание речи (Whisper) ──────────────────────────────────────────────


@router.post('/audio/transcriptions')
async def studio_audio_transcriptions(
    file: UploadFile = File(...), model: str | None = None, language: str | None = None
):
    """Расшифровка аудио через whisper.cpp-движок студии (управляющий API launcher.'а)."""
    content = await file.read()
    form = aiohttp.FormData()
    form.add_field(
        'audio', content, filename=file.filename or 'audio.wav', content_type=file.content_type or 'audio/wav'
    )
    if model:
        form.add_field('model', model)
    if language:
        form.add_field('language', language)

    try:
        async with aiohttp.ClientSession(timeout=REQUEST_TIMEOUT) as session:
            async with session.post(f'{STUDIO_BASE}/api/speech/transcribe', data=form) as upstream:
                if upstream.status != 200:
                    raise HTTPException(status_code=upstream.status, detail=await upstream.text())
                data = await upstream.json()
    except aiohttp.ClientError as e:
        raise HTTPException(status_code=503, detail=f'Whisper-движок студии недоступен: {e}')

    text = data.get('text') or data.get('transcription') or ''
    return {'text': text, **{k: v for k, v in data.items() if k not in ('text', 'transcription')}}


# ── Аудио: синтез речи (Kokoro TTS) ──────────────────────────────────────────────────


@router.post('/audio/speech')
async def studio_audio_speech(payload: dict = Body(...)):
    """TTS через Kokoro-движок студии. Возвращает WAV-аудио (как OpenAI /audio/speech)."""
    text = payload.get('input') or payload.get('text') or ''
    if not text:
        raise HTTPException(status_code=400, detail="Поле 'input' (текст) обязательно.")

    body = {'text': text}
    if payload.get('voice'):
        body['voice'] = payload['voice']
    if payload.get('speed'):
        body['speed'] = payload['speed']

    try:
        async with aiohttp.ClientSession(timeout=REQUEST_TIMEOUT) as session:
            async with session.post(f'{STUDIO_BASE}/api/tts/speak', json=body) as upstream:
                if upstream.status != 200:
                    raise HTTPException(status_code=upstream.status, detail=await upstream.text())
                ctype = upstream.headers.get('Content-Type', 'audio/wav')
                audio_bytes = await upstream.read()
    except aiohttp.ClientError as e:
        raise HTTPException(status_code=503, detail=f'Kokoro TTS-движок студии недоступен: {e}')

    from fastapi.responses import Response

    return Response(content=audio_bytes, media_type=ctype)


# ── Прямое управление жизненным циклом движков (проброс к launcher-API студии) ───────

_CONTROL_ROUTES = {
    'llm/start': ('POST', '/api/llm/start'),
    'llm/stop': ('POST', '/api/llm/stop'),
    'llm/status': ('GET', '/api/llm/status'),
    'speech/start': ('POST', '/api/speech/start'),
    'speech/stop': ('POST', '/api/speech/stop'),
    'speech/status': ('GET', '/api/speech/status'),
    'tts/start': ('POST', '/api/tts/start'),
    'tts/stop': ('POST', '/api/tts/stop'),
    'tts/status': ('GET', '/api/tts/status'),
    'telemetry': ('GET', '/api/telemetry'),
    'hardware-specs': ('GET', '/api/hardware-specs'),
    'outputs': ('GET', '/api/outputs'),
    'web-search': ('POST', '/api/web-search'),
}


@router.api_route('/control/{action:path}', methods=['GET', 'POST'])
async def studio_control(action: str, request: Request):
    """Проброс управляющих команд к серверу-оркестратору студии (serve.cjs).

    Примеры: ``POST /api/v1/studio/control/llm/start``, ``GET /api/v1/studio/control/telemetry``.
    """
    route = _CONTROL_ROUTES.get(action)
    if not route:
        raise HTTPException(
            status_code=404, detail=f'Неизвестное действие: {action}. Доступны: {list(_CONTROL_ROUTES)}'
        )
    method, path = route
    url = f'{STUDIO_BASE}{path}'
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=120)) as session:
            kwargs: dict[str, Any] = {}
            if method == 'POST':
                try:
                    kwargs['json'] = await request.json()
                except Exception:
                    kwargs['json'] = {}
            async with session.request(method, url, **kwargs) as upstream:
                return JSONResponse(await upstream.json(), status_code=upstream.status)
    except aiohttp.ClientError as e:
        raise HTTPException(status_code=503, detail=f'Сервер-оркестратор студии недоступен ({url}): {e}')
