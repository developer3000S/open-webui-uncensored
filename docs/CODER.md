# Coder — документация раздела

> Полный комплект документации раздела **Coder** согласно требованиям ТЗ
> [`Coder.md`](../Coder.md) §20: архитектура, API, схема данных и миграции,
> руководство администратора, руководство пользователя, настройка GitHub
> OAuth, runbook типовых ошибок, резервное восстановление, отчёт о
> тестировании, известные ограничения.
>
> Версия: 2.0 · Обновлено: 27 октября 2026 г.

---

## 1. Архитектурное описание решения

Раздел реализован как нативный модуль Open WebUI «backend + frontend»:

```
┌────────────────────────── браузер ──────────────────────────┐
│  /coder (Svelte 5, отдельное окно)                           │
│  ├─ Workspace: RepoPanel · чат с моделью · Changes · Export  │
│  │            · Sandbox Preview (iframe, hot-reload, publish)│
│  ├─ Environment: GitHub-подключения · репозитории · аудит    │
│  └─ Projects: сохранённые проекты · режимы/шаблоны · задачи  │
└──────────────┬───────────────────────────────────────────────┘
               │ REST (src/lib/apis/coder/index.ts)
┌──────────────▼─────────────── backend (FastAPI) ─────────────┐
│  routers/coder.py                                            │
│   ├─ auth/connections (OAuth flow, несколько аккаунтов/GHES) │
│   ├─ repos/branches/tree/file/search(+/semantic)/files batch │
│   ├─ changeset/validate · export/preview · export/start(jobs)│
│   ├─ export/gist · pr comments · ci/status · tests/suggest   │
│   ├─ modes · sandbox/session CRUD+pause/resume/destroy       │
│   ├─ sandbox file editor · changeset apply · preview ·       │
│   │  publish · /preview/s/{share_id} (public) · sweep        │
│   ├─ tasks (pin/archive/search/title/followups)              │
│   ├─ stream/metrics · projects (CRUD) · audit                │
│   ├─ admin/audit · admin/policies · metrics (Prometheus)     │
│  utils/coder/                                                │
│   ├─ github_client.py  — REST GitHub/GHES, retry-политики    │
│   ├─ changeset.py      — валидация путей/лимитов, diff       │
│   ├─ policy.py         — админ-политики (allow/block-листы)  │
│   ├─ semantic.py       — семантический поиск (эмбеддинги +   │
│   │                      lexical fallback, кэш эмбеддингов)  │
│   ├─ sandbox.py        — изолированная FS-песочница задачи,  │
│   │                      preview/publish (план coder.qwen.ai)│
│   ├─ modes.py          — режимы генерации + шаблоны-старты,  │
│   │                      title/tags, follow-up предложения   │
│   ├─ export_worker.py  — асинхронный экспорт (asyncio task)  │
│   └─ metrics.py        — prometheus-счётчики coder_* (+стрим)│
│  models/coder.py       — SQLAlchemy-модели + Pydantic-схемы  │
│  migrations/versions/  — Alembic (5 ревизий coder_*)         │
└──────────────┬───────────────────────────────────────────────┘
               │ HTTPS (токены хранятся только на сервере)
        api.github.com / <GHES host>/api/v3
```

Ключевые свойства:

- **Feature flag.** Весь раздел включается только при `CODER_ENABLED=true`;
  при выключенном флаге API возвращает 403, пункт меню скрыт.
- **Токены не покидают сервер.** OAuth-токены шифруются AES-256-GCM
  (`CODER_ENCRYPTION_KEY`, fallback — производный от `WEBUI_SECRET_KEY`) и
  никогда не отдаются фронтенду; все вызовы GitHub выполняет бэкенд.
- **Прогрессивная загрузка контекста.** Модель получает полное дерево
  файлов + «скелет» ключевых файлов (~12) в бюджете ~48 000 символов;
  остальное читает через `repo_search` / пакетную догрузку файлов.
- **Обязательный PR.** Экспорт пишет коммит в новую ветку через Git Data
  API и всегда создаёт Pull Request (политика `CODER_REQUIRE_PR`).
- **Асинхронный экспорт (NFR-08).** `/export/start` регистрирует job и
  исполняет его фоновой asyncio-задачей (`export_worker.schedule_export`);
  статус — через `GET /export/jobs/{id}`.
- **Наблюдаемость.** Correlation ID (`X-Request-ID` или генерируется),
  IP/User-Agent в каждом событии аудита, Prometheus-метрики `coder_*`.
- **Sandbox + живой Preview (план coder.qwen.ai, приоритет A).** Каждая задача
  может получить изолированную файловую песочницу (`DATA_DIR/sandboxes/<id>`)
  со стартовым скелетом выбранного режима/шаблона; панель Preview рендерит
  проект через iframe-эндпоинт (hot-reload по cache-buster `?v=`), публикация
  одним кликом создаёт публичную страницу `/preview/s/{share_id}`.
- **Режимы и шаблоны генерации (приоритет B).** Пресеты Web Dev / Data
  Visualization / Visual Design / Prototype с собственными системными промптами
  и скелетами; автоназвания/теги задач и follow-up предложения.
- **Управление задачами (приоритет C).** Метаданные чатов Coder
  (`coder_task_meta`): pin/unpin, archive/restore, глобальный поиск, статусы.
- **Метрики стрима (приоритет E).** Фронтенд сообщает first-chunk time и число
  чанков (`POST /stream/metrics`) → Prometheus-гистограммы + событие аудита
  `generation_streamed`.

## 2. Описание API

Все эндпоинты — `/api/v1/coder/...`, требуют `get_verified_user`
(кроме помеченных *admin*), возвращают JSON. Обозначения параметров:
`connection_id` — опциональный id конкретного GitHub-подключения
(по умолчанию используется default-подключение пользователя).

### 2.1. Конфигурация и администрирование

| Метод | Путь | Описание |
|---|---|---|
| GET | `/config` | Состояние feature flag, публичные лимиты, политики (без секретов); пишет `section_accessed` |
| GET | `/admin/policies` | *admin* — действующие политики из config/DB |
| GET | `/metrics` | *admin* — Prometheus-exposition счётчиков `coder_*` |
| GET | `/admin/audit` | *admin* — события аудита по всем пользователям (фильтры `user_id`, `action`, `limit`) |

### 2.2. GitHub-подключения (несколько аккаунтов / GHES)

| Метод | Путь | Описание |
|---|---|---|
| GET | `/github/auth/start?host=` | Редирект на OAuth; `host` — домен GHES (пусто = github.com) |
| GET | `/github/auth/callback` | Callback; обмен кода, шифрование и сохранение токена |
| GET | `/github/connection` | Default-подключение текущего пользователя |
| GET | `/github/connections` | Все подключения пользователя (login, host, scopes, is_default) |
| POST | `/github/connections/{id}/default` | Сделать подключение default |
| DELETE | `/github/connections/{id}` | Отключить аккаунт (при удалении default следующий становится default) |
| DELETE | `/github/connection` | Удалить default-подключение |

### 2.3. Репозиторий и файлы

| Метод | Путь | Описание |
|---|---|---|
| GET | `/repos?q=&page=` | Список репозиториев пользователя (с учётом `CODER_ALLOWED_ORGS/REPOS`) |
| GET | `/branches?owner=&repo=` | Ветки репозитория |
| GET | `/tree?owner=&repo=&branch=` | Дерево файлов (создаёт/обновляет `coder_project`) |
| GET | `/file?owner=&repo=&path=&branch=` | Содержимое файла (блок-лист путей, rate limit) |
| POST | `/files/batch` | Пакетная догрузка файлов в контекст модели |
| GET | `/search?q=&glob=&max_results=` | Серверный grep-style поиск по содержимому (инструмент `repo_search`) |
| GET | `/search/semantic?q=&owner=&repo=&branch=` | Семантический поиск (эмбеддинги модели с lexical fallback и кэшем) |

### 2.4. Change Set и экспорт

| Метод | Путь | Описание |
|---|---|---|
| POST | `/changeset/validate` | Валидация Change Set (пути, лимиты 50 файлов / 1 МиБ/файл / 5 МиБ суммарно, rename; предупреждения secret-scanner'а возвращаются отдельно) |
| POST | `/export/preview` | Unified diff без записи в GitHub |
| POST | `/export/start` | Создание export job + асинхронный экспорт (ветка → blob/tree/commit → PR); идемпотентность по `idempotency_key` |
| GET | `/export/jobs` | Список jobs пользователя |
| GET | `/export/jobs/{id}` | Статус job (`pending/running/completed/failed`, commit_sha, pr_url) |
| POST | `/export/gist` | Экспорт файлов в Gist (`public`/`secret`) |

### 2.5. PR, CI, тесты, проекты, аудит

| Метод | Путь | Описание |
|---|---|---|
| GET | `/pr/{owner}/{repo}/{n}/comments` | Review-комментарии PR |
| POST | `/pr/{owner}/{repo}/{n}/comments` | Добавить review-комментарий (path/line/body) |
| GET | `/ci/status?owner=&repo=&branch=` | Совокупный статус CI (check-runs + commit statuses) |
| POST | `/tests/suggest` | Автогенерация тестов моделью + создание issue в репозитории |
| GET/POST | `/projects` | Список / создание сохраняемого проекта |
| GET/DELETE | `/projects/{id}` | Карточка / удаление проекта |
| GET | `/audit` | Журнал аудита текущего пользователя |
| POST | `/audit/cleanup` | Принудительная очистка по retention (`CODER_AUDIT_RETENTION_DAYS`) |

### 2.7. Режимы и шаблоны генерации (план §B)

| Метод | Путь | Описание |
|---|---|---|
| GET | `/modes` | Список режимов (web-dev / data-viz / visual-design / prototype: label, description, skeleton) + галерея шаблонов-стартов («Build a Snake Game», «Create a Pomodoro Timer» и т.п.) |

### 2.8. Sandbox-сессии и живой Preview (план §A)

| Метод | Путь | Описание |
|---|---|---|
| POST | `/sandbox/session` | Создать песочницу задачи (`{mode?, template_id?}`); разворачивает скелет режима/шаблона в `DATA_DIR/sandboxes/<id>`; статус `active` |
| GET | `/sandbox/sessions` | Активные/приостановленные сессии пользователя |
| GET | `/sandbox/session/{id}` | Карточка сессии + список файлов |
| POST | `/sandbox/session/{id}/pause` · `/resume` | Перевод статуса (pause/resume) |
| DELETE | `/sandbox/session/{id}` | Destroy — удаление директории и пометка сессии |
| GET | `/sandbox/session/{id}/file?path=` | Чтение файла (§A3 браузерный редактор) |
| PUT | `/sandbox/session/{id}/file` | Запись файла `{path, content}` (лимиты и блок-лист путей) |
| DELETE | `/sandbox/session/{id}/file?path=` | Удаление файла внутри песочницы |
| POST | `/sandbox/session/{id}/changeset` | Применить change set модели к песочнице (частично — Stop откатывает только неприменённые файлы) |
| GET | `/sandbox/session/{id}/preview?v=` | HTML живой превью-панели (iframe src; `v` — cache-buster hot-reload) |
| POST | `/sandbox/session/{id}/publish` | Публикация одним кликом → `{share_id, url}`; повторный вызов = redeploy |
| GET | `/preview/s/{share_id}` | **Без авторизации** — публичная страница результата (аналог `/c/<id>` у Qwen) |
| POST | `/sandbox/sweep` | *admin* — TTL-чистка протухших сессий (строки старше `CODER_SANDBOX_TTL_MINUTES` + осиротевшие директории); можно повесить на cron |

### 2.9. Управление задачами (план §C, §B3/B4)

| Метод | Путь | Описание |
|---|---|---|
| GET | `/tasks?archived=&q=&tag=` | Список задач пользователя: pin-сортировка, фильтр архива, глобальный поиск по title/tags, фильтр по тегу |
| POST | `/tasks/{chat_id}` | Upsert метаданных: `{title?, tags?, mode?, status?, is_pinned?, is_archived?}` (pin/unpin, archive/restore) |
| DELETE | `/tasks/{chat_id}` | Удалить метаданные задачи |
| POST | `/tasks/{chat_id}/title?prompt=` | Автоназвание + автотеги задачи из первого промпта (§B3) |
| GET | `/tasks/{chat_id}/followups?mode=` | Follow-up предложения «что сделать дальше» под ответом модели (§B4) |

### 2.10. Метрики стрима генерации (план §E)

| Метод | Путь | Описание |
|---|---|---|
| POST | `/stream/metrics?first_chunk_ms=&chunks=&mode=` | UI сообщает время первого чанка и число чанков → Prometheus-гистограммы `coder_stream_first_chunk_seconds` / `coder_stream_chunks_total` + событие аудита `generation_streamed` |

### 2.6. Общие соглашения

- Ошибки: `{"detail": "...", "code": "..."}`; код `CODER_AUTH_*` — проблемы
  подключения/токена, `RATE_LIMITED` — превышение лимита запросов к файлам,
  `SandboxError`-коды песочницы (`invalid_path`, `blocked_path`,
  `CODER_SANDBOX_LIMIT` и т.п.) — нарушения границ/лимитов sandbox.
- Каждый значимый вызов принимает correlation ID из заголовка
  `X-Request-ID` (иначе генерируется uuid4) и пишет событие в
  `coder_audit_event` вместе с IP и User-Agent.
- Полный список событий аудита: `section_accessed`, `github_connect`,
  `github_disconnect`, `github_connection_default_changed`,
  `github_connection_deleted`, `repo_selected`, `file_viewed`,
  `permission_denied`, `rate_limited`, `semantic_search`,
  `review_comments_listed`, `review_comment_created`, `ci_status_viewed`,
  `gist_exported`, `test_issue_created`, `project_created`,
  `project_deleted`, `export_start`, `export_completed`, `export_failed`,
  `audit_cleanup`; план coder.qwen.ai: `sandbox_created`,
  `sandbox_destroyed`, `sandbox_changeset_applied`, `sandbox_published`,
  `sandbox_sweep`, `task_meta_updated`, `generation_streamed`.

### 2.7. Режимы и шаблоны генерации (план §B)

| Метод | Путь | Описание |
|---|---|---|
| GET | `/modes` | Список режимов (web-dev / data-viz / visual-design / prototype: label, description, skeleton) + галерея шаблонов-стартов («Build a Snake Game», «Create a Pomodoro Timer» и т.п.) |

### 2.8. Sandbox-сессии и живой Preview (план §A)

| Метод | Путь | Описание |
|---|---|---|
| POST | `/sandbox/session` | Создать песочницу задачи (`{mode?, template_id?}`); разворачивает скелет режима/шаблона в `DATA_DIR/sandboxes/<id>`; статус `active` |
| GET | `/sandbox/sessions` | Активные/приостановленные сессии пользователя |
| GET | `/sandbox/session/{id}` | Карточка сессии + список файлов |
| POST | `/sandbox/session/{id}/pause` · `/resume` | Перевод статуса (pause/resume) |
| DELETE | `/sandbox/session/{id}` | Destroy — удаление директории и пометка сессии |
| GET | `/sandbox/session/{id}/file?path=` | Чтение файла (§A3 браузерный редактор) |
| PUT | `/sandbox/session/{id}/file` | Запись файла `{path, content}` (лимиты и блок-лист путей) |
| DELETE | `/sandbox/session/{id}/file?path=` | Удаление файла внутри песочницы |
| POST | `/sandbox/session/{id}/changeset` | Применить change set модели к песочнице (частично — Stop откатывает только неприменённые файлы) |
| GET | `/sandbox/session/{id}/preview?v=` | HTML живой превью-панели (iframe src; `v` — cache-buster hot-reload) |
| POST | `/sandbox/session/{id}/publish` | Публикация одним кликом → `{share_id, url}`; повторный вызов = redeploy |
| GET | `/preview/s/{share_id}` | **Без авторизации** — публичная страница результата (аналог `/c/<id>` у Qwen) |
| POST | `/sandbox/sweep` | *admin* — TTL-чистка протухших сессий (строки старше `CODER_SANDBOX_TTL_MINUTES` + осиротевшие директории); можно повесить на cron |

### 2.9. Управление задачами (план §C, §B3/B4)

| Метод | Путь | Описание |
|---|---|---|
| GET | `/tasks?archived=&q=&tag=` | Список задач пользователя: pin-сортировка, фильтр архива, глобальный поиск по title/tags, фильтр по тегу |
| POST | `/tasks/{chat_id}` | Upsert метаданных: `{title?, tags?, mode?, status?, is_pinned?, is_archived?}` (pin/unpin, archive/restore) |
| DELETE | `/tasks/{chat_id}` | Удалить метаданные задачи |
| POST | `/tasks/{chat_id}/title?prompt=` | Автоназвание + автотеги задачи из первого промпта (§B3) |
| GET | `/tasks/{chat_id}/followups?mode=` | Follow-up предложения «что сделать дальше» под ответом модели (§B4) |

### 2.10. Метрики стрима генерации (план §E)

| Метод | Путь | Описание |
|---|---|---|
| POST | `/stream/metrics?first_chunk_ms=&chunks=&mode=` | UI сообщает время первого чанка и число чанков → Prometheus-гистограммы `coder_stream_first_chunk_seconds` / `coder_stream_chunks_total` + событие аудита `generation_streamed` |

## 3. Схема данных и миграции

Таблицы (Alembic, применяются автоматически при старте):

| Таблица | Назначение | Ключи/индексы |
|---|---|---|
| `coder_github_connection` | Шифрованные OAuth-токены; несколько аккаунтов на пользователя | PK `id`; уникальность `(user_id, github_host)`; `is_default` |
| `coder_project` | Сохраняемые проекты (owner/repo/default_branch/meta) | PK `id`; `uq_coder_project_user_repo` |
| `coder_export_job` | Задачи экспорта со снапшотом Change Set и статусом | PK `id`; `idempotency_key` unique; индексы user/status |
| `coder_audit_event` | Журнал аудита (action/target/payload без секретов, correlation_id, ip_address, user_agent) | PK `id`; индексы user/created_at |
| `coder_sandbox_session` | Песочницы задач (план §A): статус `active/paused/destroyed`, режим, `published_share_id` | PK `id`; индекс `user_id` |
| `coder_task_meta` | Метаданные задач Coder (план §C/B3): title/tags/mode/status, `is_pinned`, `is_archived` | PK `id`; уникальность `(user_id, chat_id)`; индекс `user_id` |

Ревизии:

1. `c0d3r4b17e21` — создание четырёх таблиц MVP.
2. `c0d3r4ud1t01` — поля контекста аудита `correlation_id`, `ip_address`, `user_agent` (§11.4).
3. `c0d3r4m1c7h1` — мульти-GitHub: колонки `github_host`, `is_default`,
   backfill существующих строк (`github.com`, default), замена уникальности
   `user_id` на `(user_id, github_host)`. Реализовано через
   `batch_alter_table` — совместимо с SQLite и PostgreSQL.
4. `c0d3r45ndb0x` — план coder.qwen.ai: таблицы `coder_sandbox_session`
   (жизненный цикл песочниц, публикация) и `coder_task_meta`
   (pin/archive/поиск/статусы задач). Также совместима с SQLite/PostgreSQL.

Downgrade миграции 3 схлопывает несколько подключений в одно перед
восстановлением старой уникальности (см. файл миграции); downgrade миграции 4
удаляет обе таблицы плана.

## 4. Руководство администратора

### 4.1. Переменные окружения (`.env`)

Включение и креденшелы:

| Переменная | По умолчанию | Назначение |
|---|---|---|
| `CODER_ENABLED` | `false` | Feature flag раздела |
| `CODER_GITHUB_CLIENT_ID` / `CODER_GITHUB_CLIENT_SECRET` | пусто | GitHub OAuth App |
| `CODER_GITHUB_API_BASE_URL` | `https://api.github.com` | Базовый URL REST API (для GHES задавать не нужно — хост берётся из подключения) |
| `CODER_ENCRYPTION_KEY` | пусто (fallback: derived from `WEBUI_SECRET_KEY`) | Ключ AES-256-GCM для токенов; ≥32 символов |

Лимиты Change Set (§13.4):

| Переменная | По умолчанию |
|---|---|
| `CODER_MAX_FILES_PER_CHANGESET` | `50` |
| `CODER_MAX_FILE_SIZE` | `1048576` (1 МиБ на файл) |
| `CODER_MAX_TOTAL_DIFF_SIZE` | `5242880` (5 МиБ суммарно) |
| `CODER_MAX_DIFF_LINES` | `4000` |

Политики (§15.1):

| Переменная | По умолчанию | Назначение |
|---|---|---|
| `CODER_ALLOWED_GITHUB_HOSTS` | `github.com,api.github.com` | Разрешённые хосты (добавьте домен GHES для поддержки Enterprise) |
| `CODER_ALLOWED_ORGS` | пусто (все) | Allow-list владельцев/orgs |
| `CODER_ALLOWED_REPOS` | пусто (все) | Allow-list `owner/repo` |
| `CODER_BLOCKED_PATHS` | `.env,*.pem,secrets/*,.git/*` | Блок-лист путей в Change Set |
| `CODER_REQUIRE_PR` | `true` | Обязательный PR (прямые push запрещены конструкцией) |

Secret scanning (§13.5) выполняется общим сканером `retrieval/secret_scanning.py`
(режим задаётся переменной `RAG_SECRET_SCANNING_MODE`: `warn` / `block` / `off`;
детекция AWS-ключей, private keys, GitHub/Slack токенов, JWT, строк подключения БД и др.).

Надёжность и наблюдаемость:

| Переменная | По умолчанию | Назначение |
|---|---|---|
| `CODER_ASYNC_EXPORT` | `true` | Фоновый экспорт вместо синхронного HTTP |
| `CODER_GITHUB_RETRY_POLICY` | `exponential` | Политика повторов (`fixed` \| `exponential`) |
| `CODER_GITHUB_RETRY_MAX` | `3` | Число повторов при 5xx/transport errors |
| `CODER_GITHUB_RETRY_DELAY` | `1` | Базовая задержка, сек |
| `CODER_GITHUB_TIMEOUT` | `30` | Таймаут запроса к GitHub, сек |
| `CODER_AUDIT_RETENTION_DAYS` | `90` | Хранение журнала аудита (cleanup — `POST /audit/cleanup` или cron) |

Песочницы и публикация (план coder.qwen.ai, §A):

| Переменная | По умолчанию | Назначение |
|---|---|---|
| `CODER_SANDBOX_ROOT` | пусто (`DATA_DIR/sandboxes`) | Корень изолированных песочниц задач |
| `CODER_SANDBOX_TTL_MINUTES` | `60` | TTL песочницы; протухшие удаляются `POST /sandbox/sweep` (admin/cron) |
| `CODER_SANDBOX_MAX_FILES` | `200` | Максимум файлов в одной песочнице |
| `CODER_SANDBOX_MAX_FILE_SIZE` | `524288` (512 КиБ) | Максимум на один файл песочницы |
| `CODER_SANDBOX_MAX_TOTAL_SIZE` | `20971520` (20 МиБ) | Суммарный лимит песочницы |
| `CODER_PUBLISH_ROOT` | пусто (`DATA_DIR/published`) | Корень опубликованных страниц |
| `CODER_PUBLISH_URL_PREFIX` | `/api/v1/coder/preview` | Префикс публичного URL публикации (`…/s/{share_id}`) |

Пути внутри песочницы проходят тот же блок-лист, что и Change Set
(`CODER_BLOCKED_PATHS` → `.env`, `*.pem`, `secrets/*` и т.д.); все пути
канонизируются с защитой от path traversal.

> [!WARNING]
> Прочие исторические имена (`CODER_GITHUB_PROVIDER`, `CODER_GITHUB_APP_ID`,
> `CODER_GITHUB_APP_PRIVATE_KEY_PATH`, `CODER_GITHUB_ENTERPRISE_MODE`,
> `CODER_MAX_FILE_SIZE_BYTES`, `CODER_MAX_TOTAL_CHANGES_BYTES`,
> `CODER_MAX_FILES_PER_EXPORT`, `CODER_REQUIRE_PULL_REQUEST`,
> `CODER_DEFAULT_MODEL`) бэкендом **не читаются** — не используйте их.

### 4.2. Проверка конфигурации

- `GET /api/v1/config` → поле `features.enable_coder`;
- `GET /api/v1/coder/admin/policies` (admin) — фактические действующие
  политики (config с приоритетом над значениями по умолчанию);
- `GET /api/v1/coder/metrics` (admin) — Prometheus-метрик:
  `coder_requests_total`, `coder_github_requests_total`,
  `coder_export_jobs_total`, `coder_export_duration_seconds`,
  `coder_audit_events_total`, `coder_github_connections`,
  `coder_rate_limited_total` (при отсутствии пакета `prometheus_client`
  возвращается текстовая заглушка — раздел остаётся работоспособным).
- Обзор аудита всех пользователей: `GET /api/v1/coder/admin/audit`
  (в UI — вкладка Environment → секция Audit).

### 4.3. Rotation `CODER_ENCRYPTION_KEY`

Смена ключа делает ранее сохранённые токены нечитаемыми. Порядок:

1. уведомить пользователей и попросить переподключить GitHub;
2. обновить `.env`, перезапустить контейнер;
3. проблемные соединения удаляются через `DELETE /github/connections/{id}`.

## 5. Руководство пользователя

1. **Подключение.** Coder → Environment → «Connect GitHub». Можно
   подключить несколько аккаунтов/хостов (GitHub Cloud и GHES) — для этого
   в форме «Connect another GitHub» укажите домен Enterprise-хоста
   (например, `git.corp.example`), затем Authorize. Одно подключение
   помечено **default**; переключить — кнопкой «Make default».
2. **Рабочее пространство.** Выберите репозиторий во вкладке Environment —
   он подгружается в Workspace (ветки, дерево, скелет ключевых файлов).
   Задайте задачу в чате; модель может запрашивать дополнительный код —
   поиск выполняется автоматически (`repo_search`). Кнопка **Clear chat**
   сбрасывает историю.
3. **Поиск.** В панели репозитория доступны обычный (grep-style) и
   **семантический** поиск по содержимому репозитория.
4. **Изменения.** Ответ модели с Change Set показывает unified diff во
   вкладке Changes; действия `create/update/delete/rename` (`old_path` для
   rename). Перед экспортом — обязательная серверная валидация.
5. **Экспорт.** «Export to GitHub» → новая ветка + **обязательный PR**
   (прогресс — в списке export jobs, статус обновляется асинхронно).
   Альтернатива — быстрый **экспорт в Gist** (public/secret).
6. **PR-инструменты.** Для открытого PR доступны просмотр и добавление
   review-комментариев, проверка **CI-статуса** ветки, автогенерация
   тестов с созданием issue.
7. **Проекты.** Закреплённые репозитории сохраняются как проекты
   (вкладка Projects) — с метаданными и быстрым возвратом в Workspace.
8. **Sandbox и Preview (план coder.qwen.ai).** В Workspace можно создать
   изолированную песочницу задачи: выбрать режим (Web Dev / Data
   Visualization / Visual Design / Prototype) или готовый шаблон-старт
   («Build a Snake Game», «Create a Pomodoro Timer» и т.п.) — каркас
   разворачивается автоматически, панель **Preview** показывает живой
   результат в iframe (кнопка refresh = hot-reload). Change Set модели
   применяется к песочнице кнопкой «Apply to sandbox»; файлы правятся через
   браузерный редактор. **Publish** публикует проект по публичному адресу
   `/api/v1/coder/preview/s/<share_id>` (повторная публикация = redeploy).
   Песочницы живут `CODER_SANDBOX_TTL_MINUTES` и чистятся админским sweep.
9. **Задачи.** Каждая сессия Coder имеет метаданные: автоназвание и теги
   (§B3), статус running/done/error, pin/unpin и archive/restore, глобальный
   поиск и фильтр по тегам; после ответа модели показываются follow-up
   предложения «что сделать дальше».
10. **Аудит.** Личный журнал действий — Environment → Audit.

## 6. Настройка GitHub App / OAuth

Раздел использует **GitHub OAuth App** (не GitHub App):

1. GitHub → Settings → Developer settings → OAuth Apps → New OAuth App.
2. **Authorization callback URL:**
   `{BASE_URL}/api/v1/coder/github/auth/callback`
   (локально по умолчанию `http://localhost:8083/api/v1/coder/github/auth/callback`).
3. Скопируйте Client ID/Secret в `.env`, перезапустите контейнер.
4. Требуемые scope OAuth приложения: `repo` (чтение/запись контента —
   включает Contents: Read & Write на всех доступных репозиториях),
   `public_repo` (страховочный scope для публичных репозиториев),
   `gist`, `read:org` (опционально для allow-list orgs).
   Приложение запрашивает `scope=repo public_repo` по умолчанию, поэтому при
   согласии пользователя токен покрывает **все** репозитории с доступом к
   содержимому (Contents: Read & Write; чтения Contents: Read это надмножество,
   отдельного read-only репозиторного scope у OAuth-приложений GitHub нет).
   GitHub не позволяет предвыбрать переключатель «Repository access»
   параметрами URL авторизации — экран согласия всегда открывается с
   «Public Repositories (read-only)», поэтому **на экране согласия нужно
   выбрать «All repositories»** (иначе приватные репозитории в список не
   попадут). Сервер подстраховывает это автоматически: после возврата OAuth
   проверяет выданный scope (`repo`) и делает тестовый запрос `/user/repos`;
   при нехватке прав пользователь перенаправляется обратно на consent-экран
   (`github_retry_auth=1`) либо получает `github_error=insufficient_scopes`,
   а UI показывает подсказку reconnect с «Repository access: All repositories»
   и Contents: Read.
5. **Организации:** администратор организации должен в Settings → Third-party
   App access одобрить приложение и выбрать «All repositories», иначе список
   репозиториев организации будет пустым даже при корректном токене.
6. **GitHub Enterprise Server:** установите OAuth-приложение на самом
   GHES-хосте (`https://<host>/settings/developers applications`), добавьте
   домен в `CODER_ALLOWED_GITHUB_HOSTS`, после чего пользователи смогут
   авторизоваться, указав хост в «Connect another GitHub». Клиент сам
   строит API-base `https://<host>/api/v3`.

## 7. Runbook типовых ошибок

| Симптом | Причина | Действие |
|---|---|---|
| HTML вместо JSON в API (ошибка «Unexpected token '<', "<!doctype"») | Бэкенд не поднял роутер `/coder` (исключение при импорте) или запрос идёт не на API-порт | См. шаг 1–2 ниже; проверьте лог сервера на `ImportError/SyntaxError` в `routers.coder` |
| `redirect_uri_mismatch` | Callback URL в OAuth-приложении не совпадает с `{BASE_URL}/api/v1/coder/github/auth/callback` | Обновить callback в приложении GitHub |
| `CODER_AUTH_*` после успешного OAuth | Истёк/отозван токен, неверные креденшелы клиента, блок доступа организации | Переподключить GitHub; проверить `?github_error=` в редиректе и `/audit` |
| Список репозиториев пуст после подключения GitHub | На экране согласия выбрано «Only select repositories» / «Public Repositories (read-only)» вместо «All repositories», либо организация не одобрила приложение | Переподключиться и выбрать **Repository access → All repositories** (Contents: Read&Write покрывается scope `repo`); для организаций — одобрить приложение в Third-party App access; сервер сам редиректит на повторный consent при нехватке scope (`github_retry_auth=1`) |
| `403 feature disabled` | `CODER_ENABLED=false` или контейнер не перезапущен после правки `.env` | Включить флаг, перезапустить |
| «host not allowed» (`permission_denied`) | Домен не входит в `CODER_ALLOWED_GITHUB_HOSTS` | Добавить домен GHES в переменную |
| Protected branch / запись в main отказана | Это ожидаемое поведение: экспорт всегда идёт в новую ветку + PR | Открыть PR на ревью |
| `RATE_LIMITED` | Превышен лимит обращений к файлам за сессию | Повторить позже; использовать `repo_search` вместо массового чтения |
| Экспорт завис в `running` | Фоновая задача упала при рестарте процесса | Открыть job повторно (`/export/jobs/{id}`), при необходимости запустить экспорт заново — `idempotency_key` защитит от дублей |
| Таблицы `coder_*` отсутствуют | Миграции не применены | `alembic upgrade head` в окружении бэкенда (миграция `c0d3r4m1c7h1` обязательна для мульти-подключений, `c0d3r45ndb0x` — для sandbox/задач) |
| Токены нечитаемы после смены key | Rotation `CODER_ENCRYPTION_KEY` | Переподключить GitHub (§4.3) |
| `CODER_SANDBOX_LIMIT` / «too many files» | Превышены лимиты песочницы (200 файлов / 512 КиБ / 20 МиБ) | Удалить лишние файлы через редактор или `DELETE …/file`; увеличить `CODER_SANDBOX_MAX_*` |
| Пустое/битое превью iframe | В песочнице нет `index.html` (скелет не развёрнут, change set не применён) | Создать сессию с режимом/шаблоном либо нажать «Apply to sandbox»; обновить preview (`?v=`) |
| Публикация недоступна после рестарта | Директории `published/` вне тома `data/` при кастомном `CODER_PUBLISH_ROOT` | Убедиться, что корень публикации на persistent-томе (см. §8) |

Быстрая диагностика без браузера:

```bash
# 1. Композиция и импорт роутера
python -m py_compile backend/open_webui/routers/coder.py && \
python -c "import open_webui.routers.coder; print('IMPORT_OK')"

# 2. Миграции
alembic upgrade head

# 3. Живой маршрут (должен вернуть JSON/401, но не HTML)
curl -s -o /dev/null -w '%{http_code} %{content_type}\n' \
  -H "Authorization: Bearer $TOKEN" http://localhost:8080/api/v1/coder/projects
```

## 8. Резервное копирование и восстановление

- **Что бэкапить:** каталог `data/` (SQLite `webui.db` + загруженные файлы,
  включая подкаталоги `sandboxes/` и `published/`)
  или дамп PostgreSQL; `.env` (или secret-hранилище) — отдельно, т.к.
  содержит `CODER_ENCRYPTION_KEY` и OAuth-секреты.
- **Как:** штатный `pg_dump`/копия файла БД в остановленном состоянии либо
  LVM/snapshot-совместимая копия тома Docker (`open-webui` volume).
  Рекомендуемый план: ежедневный full + hourly WAL-checkpoint копии.
- **Восстановление:** остановить контейнер → восстановить том/БД →
  убедиться, что восстановленный `CODER_ENCRYPTION_KEY` совпадает с
  использовавшимся на момент бэкапа (иначе токены будут нечитаемы — см.
  §4.3) → запустить контейнер; Alembic применит недостающие миграции
  автоматически.
- **Проверка:** `GET /api/v1/coder/config`, `GET /github/connection`,
  `GET /export/jobs` должны отвечать штатно; тестовый dry-run экспорта —
  `POST /export/preview`.
- **Retention аудита:** `CODER_AUDIT_RETENTION_DAYS` + `POST
  /audit/cleanup` (можно повесить на cron от имени админа).

## 9. Отчёт о тестировании

Набор тестов (`backend/tests/`), все проходят локально (Python 3.12):

| Suite | Файл | Объём | Результат |
|---|---|---|---|
| Unit | `test_coder_changeset.py`, `test_coder_crypto.py` | валидация путей/Change Set, rename, лимиты 50/1MiB/5MiB, AES-GCM round-trip, детерминированный diff, secret scanning | ✅ пройдено (59) |
| Integration (mock GitHub) | `test_coder_integration.py` | OAuth callback, repo/tree/file, blob→tree→commit→ref, PR, отзыв токена, protected branch, rate limit | ✅ пройдено (8) |
| Security | `test_coder_security.py` | path traversal, IDOR, CSRF/XSS, token leakage, unauthorized export, replay, resource consumption, allow/block-листы политик | ✅ пройдено (14) |
| E2E (headless Firefox) | `test_coder_e2e.py` | загрузка `/coder`, «Connect GitHub» → github.com OAuth, `GET /api/v1/coder/config` | ✅ при запущенном контейнере с `CODER_ENABLED=true` и пользователем `e2e@test.local` |

Дополнительно (план coder.qwen.ai §A–§C): smoke-проверка композиции роутера —
47 маршрутов `/api/v1/coder/*` монтируются без ошибок импорта; sandbox-флоу
(create → write file → changeset apply → preview HTML → publish → публичная
страница `/preview/s/{share_id}` → destroy) проверен на тестовом экземпляре;
task-meta (pin/archive/поиск/title/followups) и stream-metrics эндпоинты —
через прямые вызовы. Статические проверки изменённых модулей (`py_compile`,
flake8) и компиляция Svelte-компонентов (`svelte.compile`) — без ошибок.

Ограничение: полный OAuth-поток до реального GitHub требует
зарегистрированных аккредитов; E2E проверяет только редирект. Ручная проверка
OAuth-подключения выполнена успешно 2026-10-27.

## 10. Известные ограничения

1. Авторизация — только GitHub OAuth (GitHub App не поддерживается); PAT-ввод не предусмотрен.
2. Асинхронный экспорт выполнен на asyncio-задачах внутри процесса: при жёстком рестарте сервера незавершённый job останется в статусе `running` и требует повторного запуска (идемпотентность защищает от дублей).
3. Семантический поиск деградирует до lexical-ранжирования, если эмбеддинг-эндпоинт недоступен; кэш эмбеддингов — in-process (не разделяется между репликами).
4. Поддержка GHES ограничена REST API v3 (`https://<host>/api/v3`); webhooks/GitHub App flows вне объёма.
5. Rate limiting файлов — мягкий (счётчик на пользователя/сессию), без распределённого state.
6. Retention-очистка аудита выполняется по запросу (админ/UI или cron), не фоновым планировщиком.
7. Экспорт в Gist не участвует в политиках allow-list репозиториев (Gist вне репозиторной модели).
8. Метрики Prometheus раскрываются эндпоинтом, доступным только admins; pull-скрапер Grafana/Prometheus на стороне оператора.
9. Sandbox — изолированная **файловая** песочница без выполнения кода: превью и публикация работают как статический HTML/JS в браузере (iframe), dev-сервер/Node-runtime не поднимаются; сборка фреймворковых проектов (React/Vite) не выполняется.
10. Публичная страница публикации `/preview/s/{share_id}` отдаётся **без авторизации** (как у Qwen Coder); чувствительные проекты не следует публиковать. Блок-лист путей и лимиты применяются при записи, но сам факт публикации известен по share_id.
11. TTL-чистка песочниц (`POST /sandbox/sweep`) — по запросу админа/cron, фоновый планировщик не встроен.
12. Follow-up предложения и автоназвания задач генерируются эвристически (без вызова LLM); качество названий можно переопределить вручную через `POST /tasks/{chat_id}`.
13. GitHub App (installation-токены вместо OAuth пользователя) и вход через Google/OTP — вне текущего объёма (план §D).
