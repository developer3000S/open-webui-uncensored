# Shell-скрипты проекта

Полное описание всех `.sh` файлов репозитория: Docker-деплой, локальная разработка, сборка SBOM и запуск **Uncensored AI Studio**.

---

## Содержание

- [Краткая шпаргалка](#краткая-шпаргалка)
- [Docker-скрипты (корень репозитория)](#docker-скрипты-корень-репозитория)
- [Скрипты backend](#скрипты-backend)
- [Утилиты](#утилиты)
- [Uncensored AI Studio](#uncensored-ai-studio)
- [Типичные сценарии использования](#типичные-сценарии-использования)

---

## Краткая шпаргалка

| Команда | Назначение |
|---|---|
| `./docker-run.sh` | **Рекомендуемый способ.** Собрать и запустить стек: Open WebUI + Neo4j + Uncensored AI Studio |
| `./docker-compose-run.sh` | Запуск через `docker compose` |
| `./docker-compose-launcher.sh --help` | Интерактивный запуск compose с GPU/API/данными |
| `./docker-cleanup.sh` | Удалить контейнеры **и все тома** (безвозвратно) |
| `./quick-start.sh` | Быстрый запуск готовым образом из Docker Hub |
| `./docker-ollama.sh` | Запустить контейнер Ollama |
| `./docker-update-models.sh` | Обновить все установленные модели Ollama |
| `./update.sh "commit message"` | Закоммитить и отправить изменения на GitHub |
| `./scripts/generate-sbom.sh` | Сгенерировать SBOM (CycloneDX) через Syft |
| `cd studio && ./linux.sh` | Запустить Uncensored AI Studio на Linux |
| `cd studio && ./mac.sh` | Запустить Uncensored AI Studio на macOS |
| `cd studio && ./free-mem.sh` | Очистить ОЗУ и закрыть тяжёлые процессы (root) |
| `cd studio && ./update.sh "msg"` | Отправить изменения + пересобрать фронтенд студии |
| `./studio/scripts/build/build_from_source.sh` | Скомпилировать бэкенды студии из исходников |

---

## Docker-скрипты (корень репозитория)

### `docker-run.sh` — основной локальный запуск

**Что делает:** поднимает **весь стек** — Open WebUI, Neo4j и Uncensored AI
Studio — одной командой `docker compose up -d --build` (конфигурация контейнеров
описана в `docker-compose.yaml`, а не дублируется в скрипте).

**Ключевые особенности:**

- **Обязательный `.env`** в корне репозитория — единственный источник настроек деплоя. Файл **монтируется** в контейнер (`/app/.env`), а не передаётся только через `--env-file`. Это сделано намеренно: `open_webui/env.py` перечитывает именно файл с `override=True`, чтобы имена из `.env` перекрывали таблицу `config` в SQLite. Кроме того, `--env-file` не снимает кавычки — `FORWARDED_ALLOW_IPS='*'` дошла бы до uvicorn литералом с апострофами.
- **Всегда пересобирает** образы из локальных исходников (`--build`), pull из реестра не используется; `--pull always` обновляет только базовые образы (node, neo4j).
- **Neo4j** (`neo4j:5.26`, контейнер `open-webui-neo4j`) поднимается для слоя GraphRAG (`open_webui/retrieval/graphrag`). В отличие от контейнера приложения, **не пересоздаётся** при каждом запуске — граф переживает пересборку образа. Без `NEO4J_URI` приложение работает как раньше.
- **Uncensored AI Studio** (контейнер `uncensored-studio`) собирается из `studio/Dockerfile`. Весь `studio/` пробрасывается в `/app` bind mount, так что модели и выводы остаются на диске хоста; студия доступна как напрямую по `${STUDIO_FRONTEND_PORT:-14200}`, так и из бокового меню Open WebUI (раздел **AI Студия**, iframe под `/studio/`).
- **Сеть** `open-webui-uncensored_net` общая для всех сервисов: приложение резолвит Neo4j как `bolt://open-webui-neo4j:7687`, а llama-server студии — как `http://uncensored-studio:10086/v1`. Bolt публикуется только на `127.0.0.1` для отладки с хоста (HTTP/Browser 7474 наружу не торчит).
- **Ждёт готовности** `open-webui` до 7.5 минут (90 попыток × 5 сек), при неудаче печатает логи. `open-webui` зависит от healthy-Neo4j (`depends_on` в compose), поэтому ждать остальные сервисы не нужно.

```bash
./docker-run.sh
# Порт:       OPEN_WEBUI_PORT (по умолчанию 8083)
# Neo4j Bolt: NEO4J_BOLT_PORT (по умолчанию 7687)
# Пароль Neo4j берётся из .env (NEO4J_PASSWORD)
# Студия:     STUDIO_FRONTEND_PORT (по умолчанию 14200), STUDIO_LLM_PORT (10086)
```

> ⚠️ Если в `.env` нет явного `OLLAMA_BASE_URL`, скрипт предупредит: изнутри контейнера `localhost` — это сам контейнер, а не хост. Нужен `http://host.docker.internal:11434`.

---

### `docker-compose-run.sh` — запуск через Docker Compose

**Что делает:** простой запуск проекта через `docker compose up -d --build`.

- Автовыбор `docker-compose` или плагина `docker compose`.
- Перед запуском делает `down --remove-orphans` и `docker system prune -f`.
- Освобождает порт `8083`.
- Печатает статус контейнеров и шпаргалку по командам управления.

```bash
./docker-compose-run.sh
```

---

### `docker-compose-launcher.sh` — интерактивный лаунчер compose

**Что делает:** продвинутый интерактивный лаунчер для compose-стека с автоопределением GPU, настраиваемыми портами и маунтами данных.

**Опции:**

| Опция | Описание |
|---|---|
| `--enable-gpu[count=N]` | Проброс GPU (N — число карт или `all`) |
| `--enable-api[port=PORT]` | Открыть Ollama API наружу (по умолчанию 11435) |
| `--webui[port=PORT]` | Порт WebUI (по умолчанию 8083) |
| `--data[folder=PATH]` | Bind-mount папки хоста для данных Ollama |
| `--playwright` | Включить Playwright для веб-скрапинга |
| `--build` | Пересобрать образы |
| `--drop` | Остановить и снести compose-проект |
| `-q, --quiet` | Пропустить подтверждение |

**Особенности:**

- **Автоопределение GPU-драйвера** через `nvidia-smi` / `lspci`: `nvidia`, `amdgpu`, `radeon`, `i915`. При отсутствии GPU — выход с ошибкой.
- Комбинирует несколько compose-файлов: базовый + `docker-compose.gpu.yaml`, `.api.yaml`, `.data.yaml`, `.playwright.yaml` в зависимости от опций.
- Показывает сводку конфигурации и просит подтверждения (можно обойти флагом `-q`).

```bash
./docker-compose-launcher.sh --enable-gpu[count=1] --webui[port=8080] --build
./docker-compose-launcher.sh --drop
```

---

### `docker-cleanup.sh` — полная очистка

**Что делает:** ⚠️ **останавливает все контейнеры и удаляет все Docker-тома, включая постоянные данные**. Требует подтверждения `[y/N]`.

```bash
./docker-cleanup.sh   # docker compose down -v
```

> 🔴 Это необратимая операция. Используйте только когда данные больше не нужны.

---

### `quick-start.sh` — быстрый запуск готовым образом

**Что делает:** максимально быстрый старт — использует готовый образ, если он есть локально, иначе пробует стянуть `ghcr.io/open-webui/open-webui:main`, и только в крайнем случае предлагает локальную сборку.

- Останавливает/удаляет старый контейнер `open-webui` и делает `docker system prune`.
- Освобождает порт `8083`.
- Создаёт том `open-webui` для данных.
- Спрашивает подтверждение перед долгой сборкой (10–15 мин).

```bash
./quick-start.sh
```

> 💡 В отличие от `docker-run.sh`, этот скрипт **не** требует локальной сборки и не поднимает Neo4j.

---

### `docker-ollama.sh` — запуск Ollama

**Что делает:** скачивает и запускает официальный контейнер `ollama/ollama:latest` с опциональным пробросом GPU.

- Интерактивно спрашивает про GPU passthrough (`--gpus=all`).
- Данные моделей — в томе `ollama` (`/root/.ollama`).
- Порт по умолчанию 11434 (`OLLAMA_PORT`).

```bash
./docker-ollama.sh
```

---

### `docker-update-models.sh` — обновление моделей

**Что делает:** обновляет **все** установленные в контейнере Ollama модели до актуальных версий.

- Получает список через `docker exec <container> ollama list`.
- Для каждой модели выполняет `ollama pull`.
- Имя контейнера можно переопределить: `OLLAMA_CONTAINER=my-ollama ./docker-update-models.sh`.

```bash
./docker-update-models.sh
```

---

### `update.sh` — отправка изменений на GitHub

**Что делает:** автоматический commit + push в текущую ветку.

```bash
./update.sh "Fixed log processing error"
```

- `git add .` → `git commit` → `git push origin <branch> --no-thin`
- Перед push выполняет `git gc --auto` — **флаг `--no-thin` и предварительная очистка добавлены для стабильности на внешних дисках** (exFAT и подобных).
- Push всегда идёт в **текущую** ветку (`git rev-parse --abbrev-ref HEAD`).
- Без аргумента завершается ошибкой с примером использования.

---

## Скрипты backend

### `backend/start.sh` — точка входа контейнера

**Что делает:** основной entrypoint Docker-образа. Подготавливает окружение и запускает uvicorn-сервер.

**Последовательность:**

1. **Чтение `.env`** тем же парсером, что использует приложение (`open_webui/utils/env_config.py`), а не через `source`. Причина: dotenv принимает `KEY=some value` в одной строке, а bash выполнил бы `some` как команду; docker `--env-file` оставил бы кавычки в `FORWARDED_ALLOW_IPS='*'`.
2. **Playwright** — если `WEB_LOADER_ENGINE=playwright` и не задан `PLAYWRIGHT_WS_URL`, устанавливает Chromium и докачивает `nltk punkt_tab`.
3. **Секретный ключ** — если не заданы `WEBUI_SECRET_KEY` / `WEBUI_JWT_SECRET_KEY`, генерируется ключ в файл `data/.webui_secret_key`. **Файл лежит в постоянном томе**, а не в эфемерном слое контейнера: иначе `docker compose down` уничтожит его, и при следующем старте все существующие session-токены станут недействительными. Длина настраивается через `WEBUI_SECRET_KEY_LENGTH` (по умолчанию 24).
4. **Ollama** — если `USE_OLLAMA_DOCKER=true`, запускает встроенный `ollama serve`.
5. **CUDA** — если `USE_CUDA_DOCKER=true`, расширяет `LD_LIBRARY_PATH` для torch/cudnn.
6. **HuggingFace Space** — при наличии `SPACE_ID`: поднимает сервер, ждёт `/health`, регистрирует админа через `/api/v1/auths/signup`, перезапускает сервер.
7. **Запуск uvicorn** — `uvicorn open_webui.main:app` с `--proxy-headers`, хост `0.0.0.0`, порт `8080`, число воркеров через `UVICORN_WORKERS` (по умолчанию 1). Любые аргументы командной строки перекрывают воркеры.

---

### `backend/dev.sh` — локальная разработка

**Что делает:** запускает uvicorn локально с `--reload` для разработки.

```bash
cd backend && ./dev.sh
```

Настройки берутся из `.env` репозитория — `open_webui/env.py` перечитывает его с `override=True`, поэтому экспортировать переменные здесь бессмысленно (они будут перекрыты). Для CORS в дев-режиме добавьте в `.env`:

```env
CORS_ALLOW_ORIGIN='http://localhost:5173;http://localhost:8080'
```

Порт переопределяется переменной `PORT` (по умолчанию 8080).

---

## Утилиты

### `scripts/generate-sbom.sh` — генерация SBOM

**Что делает:** создаёт спецификацию программных компонентов (SBOM) в формате **CycloneDX** с помощью **Syft**.

```bash
./scripts/generate-sbom.sh              # из манифестов зависимостей
./scripts/generate-sbom.sh docker       # из Docker-образа (лучше покрытие лицензий)
./scripts/generate-sbom.sh docker IMG   # из конкретного образа
./scripts/generate-sbom.sh validate     # проверить существующий SBOM
```

**Особенности:**

- Работает **только с разрешёнными манифестами**, а не со сканированием файловой системы: Python-зависимости резолвятся через `uv pip compile` из `backend/requirements.txt`, для JS берётся уже готовый `package-lock.json`. Так результат идентичен локально и в CI, без попадания в SBOM локального состояния и venv.
- Результат: `sbom.cdx.json` в корне.
- `validate` проверяет формат CycloneDX, наличие `specVersion`/`serialNumber` и ловит «фантомные» пакеты с локальными `file://` путями.

---

## Uncensored AI Studio

Локальный десктопный AI-комплекс (генерация изображений, LLM, распознавание речи, TTS), работающий полностью локально.

### `studio/linux.sh` — лаунчер Linux

**Что делает:** главный скрипт запуска студии на Linux. По двойному клику или из терминала.

- Грузит `.env` из `studio/`, если есть (`FRONTED_PORT`, `API_GPU`, `TEXT_API`).
- **Проверка первого запуска** и автоматический ремонт: если отсутствует portable Node.js, сборка фронтенда, бэкенды (CPU/Vulkan, llama.cpp, whisper.cpp, Kokoro TTS), запускает `scripts/setup/setup.sh` с показом причины.
- **Менеджмент `node_modules`**: если ФС поддерживает симлинки, `node_modules` → симлинк на `node_modules_linux`; иначе — swap директорий с записью платформы в `.active_modules_os` (для exFAT/FAT32).
- **Порты**: фронтенд 14200, API 8080, текстовый API 10086. Если порт фронтенда занят, перебирает 14201–14999. Порты бэкендов принудительно освобождаются.
- Запускает Node-сервер (`scripts/server/serve.cjs`), открывает браузер через `xdg-open`.
- Per-process cleanup: по `SIGINT`/`SIGTERM` корректно убивает сервер.

```bash
cd studio
./linux.sh                  # обычный запуск
./linux.sh --max-perf       # включить ROCm backend на AMD (первый запуск качает ~1.2 GB)
./linux.sh --setup-openvino # предварительно настроить Intel NPU
```

---

### `studio/mac.sh` — лаунчер macOS

**Что делает:** полный аналог `linux.sh` для macOS.

- Определяет архитектуру (`arm64` → `llm-backend/mac/arm64`, иначе `x64`) и соответствующий бэкенд Metal.
- Проверяет наличие portable Node.js, Metal-бэкенда, llama.cpp, whisper.cpp и Kokoro TTS — при отсутствии запускает `setup.sh`.
- Та же логика symlink/swap для `node_modules_mac`.
- Открывает браузер через `open`, очистка по `SIGINT`/`SIGTERM`.

```bash
cd studio
./mac.sh
```

> 💡 Запускайте только на macOS — скрипт проверяет `uname -s == Darwin`.

---

### `studio/update.sh` — обновление репозитория студии

**Что делает:** commit + push + **пересборка фронтенда студии**.

```bash
./update.sh "Your commit message"
```

Шаги:

1. `git config --global --add safe.directory /disk/llm` — фикc «dubious ownership».
2. `git add .` → `git commit -m "..."`.
3. `git gc --auto` и `git push origin main --no-thin` — стабильность на внешних дисках.
4. **Пересборка фронтенда**: `cd app/frontend` → `npm install --no-bin-links` → создание wrapper-скриптов для `vite` и `tauri` (exFAT не поддерживает симлинки) → `npm run build`.

---

### `studio/free-mem.sh` — очистка оперативной памяти

**Что делает:** интерактивная очистка ОЗУ и закрытие ресурсоёмких процессов на Linux. **Требует root** (`sudo`).

```bash
sudo ./free-mem.sh                 # интерактивный режим
sudo ./free-mem.sh -a              # только анализ/закрытие процессов
sudo ./free-mem.sh -c high         # только очистка кэшей, уровень high
sudo ./free-mem.sh 2               # уровень очистки без флагов
```

**Возможности:**

- **Статус памяти** с цветным прогресс-баром (зелёный/жёлтый/красный при >60% / >85%).
- **Анализ процессов**: топ-10 по потреблению RAM (RSS), показывает PID, пользователя, память, имя. Выводит для python/node/java/electron аргументы команд, для браузеров — тип процесса (`--type=...`).
- **Интерактивное закрытие**: выбираете номера процессов — сначала `SIGTERM`, при отсутствии ответа через 1.5 сек — `SIGKILL`. Для root-процессов требует дополнительного подтверждения.
- **Безопасность**: исключает сам скрипт, его родителя, grandparent и PID 1; пропускает процессы легче 15 MB.
- **Очистка кэшей** через `/proc/sys/vm/drop_caches`:
  - `low` (1) — pagecache + уплотнение памяти
  - `medium` (2) — pagecache + dentries/inodes + уплотнение
  - `high` (3) — полная очистка + очистка SWAP (с проверкой, что свободной RAM хватит для обратного вытеснения, иначе пропуск)
- Перед любой очисткой делает `sync` (сброс грязных кэшей на диск).
- В конце показывает, сколько памяти освободилось.

---

### `studio/app/linux.sh` — заглушка

**Что делает:** файл существует, но **абсолютно пуст** (0 байт). Не используется лаунчером — реальный запуск идёт через `studio/linux.sh` и сервер `scripts/server/serve.cjs`.

---

### `studio/scripts/setup/setup.sh` — первичная настройка студии

**Что делает:** полностью автономная настройка студии (Linux/macOS) — **без системных установок** через apt/yum/pacman и без глобального Node.js.

```bash
./studio/scripts/setup/setup.sh              # обычная настройка
./studio/scripts/setup/setup.sh --max-perf   # максимизировать GPU-производительность
```

**7 шагов:**

1. **Portable Node.js** v22.12.0 в `app/tools/node-{linux,mac}/` (скачивается официальный tarball). На ФС без симлинков создаёт shell-обёртки для npm/npx/corepack.
2. **Бэкенды stable-diffusion.cpp** (релиз `master-685-19bdfe2`):
   - macOS: Metal-бэкенд (arm64) + venv с CoreML для ANE.
   - Linux: **всегда** CPU + Vulkan; ROCm (~1.2 GB) при `--max-perf` или автоопределении AMD; CUDA — через диалог для NVIDIA.
   - **Проверка ABI**: пребилдные Linux-бинари требуют glibc ≥ 2.38 и GLIBCXX ≥ 3.4.32 (Ubuntu 24.04+). На старых системах останавливается, но при наличии gcc/g++/cmake/make/git — **компилирует из исходников**.
   - **Защита от SIGILL**: на процессорах без AVX2 отключает AVX2/FMA/BMI2/F16C при компиляции; проверяет пребилдный бинари детектором краша.
3. **llama.cpp** — делегирует в `setup-llama.sh`.
4. **whisper.cpp** — делегирует в `setup-whisper.sh`.
5. **Kokoro TTS** — делегирует в `setup-tts.sh`.
6. **npm install** для фронтенда (с symlink/swap логикой).
7. **Сборка фронтенда** в `app/dist/`.

---

### `studio/scripts/setup/setup-llama.sh` — текстовый бэкенд

**Что делает:** устанавливает бинарники `llama.cpp` (релиз `b9668`, переопределяется `LLAMA_RELEASE`).

**Платформы:**

- macOS: arm64/x64 (x64 при краше пребилда из-за отсутствия AVX2 компилируется из исходников).
- Linux x64: CUDA (при наличии nvidia-smi или GPU NVIDIA), ROCm (rocminfo/AMD), SYCL (Intel) — все **опционально** и пропускаются при неудаче; Vulkan и CPU — обязательно.
- Linux arm64: Vulkan + CPU.

При `UAIS_FORCE_COMPILE=1` — собирает все бэкенды из исходников с тем же автовыбором ISA. Vulkan-бэкенд требует установленного Vulkan SDK.

---

### `studio/scripts/setup/setup-whisper.sh` — речевой бэкенд

**Что делает:** устанавливает `whisper.cpp` (релиз `v1.9.1`, переопределяется `WHISPER_RELEASE`).

- Linux: CPU (всегда) + опционально Vulkan при `UAIS_FORCE_COMPILE=1`.
- macOS: **Homebrew** `whisper-cpp` с копированием dylib (`@rpath/libwhisper.1.dylib`) в `app/speech-backend/mac/lib` — рантайм запускает бинарь из `mac/cpu`, где `../lib` уже в rpath.
- Мигрирует старые бинари из `speech-backend/linux/` и `speech-backend/mac/` в подпапку `cpu/`.

---

### `studio/scripts/setup/setup-tts.sh` — TTS-рантайм

**Что делает:** ставит Kokoro ONNX text-to-speech в `app/tts-runtime/`.

- Создаёт минимальный `package.json` с зависимостью `kokoro-js@^1.2.1`.
- Устанавливает через **portable** npm (не системный) — он должен быть уже развёрнут `setup.sh`.
- Готовит директории `tts-models/`, `tts-outputs/`, `tts-cache/`.
- На ФС без симлинков ставит с `--no-bin-links`.

---

### `studio/scripts/setup/setup-coreml-npu.sh` — CoreML NPU (опционально)

**Что делает:** настройка CoreML для Apple Neural Engine. **Только macOS arm64.**

- Создаёт venv и ставит `python-coreml-stable-diffusion` (Apple `ml-stable-diffusion`).
- **Требует Python 3.9–3.11** — стек зависимостей Apple несовместим с 3.12+. Ищет `python3.11`/`3.10`/`3.9` или использует `COREML_SETUP_PYTHON`.
- Пересоздаёт venv, если он сделан на Python 3.12+.
- Проверяет импорт `CoreMLStableDiffusionPipeline`.

```bash
./studio/scripts/setup/setup-coreml-npu.sh
```

---

### `studio/scripts/setup/setup-openvino-npu.sh` — OpenVINO NPU (опционально)

**Что делает:** настройка Intel NPU (Core Ultra). **Только Linux x86_64.**

- Проверяет: **ядро ≥ 6.6**, наличие устройства `/dev/accel/accel0`, `python3` + venv.
- Создаёт venv, ставит `openvino`, `openvino-genai`.
- Верифицирует, что OpenVINO видит устройство `NPU`, и печатает его имя.

```bash
./studio/scripts/setup/setup-openvino-npu.sh
```

> NPU-драйвер Intel должен быть установлен **до** запуска: [intel/linux-npu-driver](https://github.com/intel/linux-npu-driver).

---

### `studio/scripts/reset/reset.sh` — сброс студии

**Что делает:** удаляет все развёрнутые зависимости студии, **сохраняя пользовательские данные**.

**Удаляет:** `app/tools/`, `app/backend/`, `app/llm-backend/`, `app/speech-backend/`, `app/tts-runtime/`, `app/dist/`, все `node_modules*` и `.active_modules_os`, `package-lock.json` фронтенда.

**Сохраняет:** модели (`models/`, `llm-models/`, `speech-models/`, `tts-models/`, `openvino-models/`), результаты (`outputs/`, `transcriptions/`, `tts-outputs/`, `tts-cache/`), историю чатов (`chat-history/`).

```bash
./studio/scripts/reset/reset.sh
```

Применять, когда нужно полностью пересоздать окружение — например, после смены ОС или при проблемах с бинарями. После сброса лаунчер при первом запуске автоматически запустит `setup.sh`.

---

### `studio/scripts/build/build_from_source.sh` — ручная сборка бэкендов

**Что делает:** компилирует бэкенды stable-diffusion.cpp из исходников для систем, где пребилдные binaries не работают. Для Linux с GLIBC < 2.38 или macOS, где нужен локальный Metal-сборка.

```bash
./studio/scripts/build/build_from_source.sh
```

**Особенности:**

- Клонирует `stable-diffusion.cpp` (пин на тег `master-685-19bdfe2`) в `app/tools/build-sd/` и инициализирует submodules.
- **macOS**: собирает Metal-бэкенд (`-DSD_METAL=ON`) и копирует `sd` + dylib в `app/backend/mac/`.
- **Linux** последовательно собирает три бэкенда в `app/backend/linux/`:
  - **CPU** → `cpu/sd-cpu`, `cpu/sd-server-cpu`
  - **Vulkan** → `vulkan/sd-vulkan`, `vulkan/sd-server-vulkan` (необязательная сборка; при неудаче — предупреждение и продолжение)
  - **CUDA** → `cuda/sd-cuda`, `cuda/sd-server-cuda`
- **Защита от SIGILL**: определяет возможности процессора через `/proc/cpuinfo` (на macOS — `sysctl machdep.cpu.features`) и при отсутствии AVX2 отключает AVX2/FMA/BMI2/F16C. Пребилдные сборки с более новых хостов падают с Illegal Instruction на старых процессорах (например, Sandy Bridge i7-2635QM с AVX только).
- Ставит `PNPM_CONFIG_NODE_LINKER=hoisted`.
- Использует все доступные ядра (`getconf _NPROCESSORS_ONLN`).

> ⚠️ На macOS x86_64 Vulkan/CUDA-секции пропускаются (сборка завершается после Metal-бэкенда).

---

## Типичные сценарии использования

### Хочу запустить Open WebUI локально

```bash
cp .env.example .env
# Отредактируйте .env: OLLAMA_BASE_URL, NEO4J_PASSWORD и т.д.
./docker-run.sh
```

Откроется на `http://localhost:8083`.

### Нужна GPU-акселерация

```bash
./docker-compose-launcher.sh --enable-gpu[count=1] --build
# Для нескольких карт:
./docker-compose-launcher.sh --enable-gpu[count=all] --webui[port=8080]
```

### Полный цикл: Ollama + Open WebUI

```bash
./docker-ollama.sh                          # поднять Ollama (порт 11434)
# В .env: OLLAMA_BASE_URL='http://host.docker.internal:11434'
./docker-run.sh                             # поднять Open WebUI
./docker-update-models.sh                   # обновить модели Ollama
```

### Запустить Uncensored AI Studio

```bash
cd studio
./linux.sh                                  # при первом запуске настроится автоматически
# Для AMD GPU с ROCm:
./linux.sh --max-perf
# Для Intel NPU:
./linux.sh --setup-openvino
```

| Сервис | Порт по умолчанию |
|---|---|
| Web UI студии | 14200 |
| API генерации изображений | 8080 |
| Текстовый API (llama.cpp) | 10086 |

### Сбросить и пересоздать студию

```bash
cd studio
./scripts/reset/reset.sh      # удалить зависимости, сохранить модели
./linux.sh                     # автоматически запустит setup.sh
```

### Очистить память перед тяжёлым инференсом

```bash
cd studio
sudo ./free-mem.sh -a          # закрыть тяжёлые процессы
sudo ./free-mem.sh -c medium   # очистить кэши
```

### Снести всё Docker-окружение

```bash
./docker-cleanup.sh            # ⚠️ удаляет контейнеры И тома с данными
```
