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
│  ├─ Environment: GitHub-подключения · репозитории · аудит    │
│  └─ Projects: сохранённые проекты                            │
└──────────────┬───────────────────────────────────────────────┘
               │ REST (src/lib/apis/coder/index.ts)
┌──────────────▼─────────────── backend (FastAPI) ─────────────┐
│  routers/coder.py                                            │
│   ├─ auth/connections (OAuth flow, несколько аккаунтов/GHES) │
│   ├─ repos/branches/tree/file/search(+/semantic)/files batch │
│   ├─ changeset/validate · export/preview · export/start(jobs)│
│   ├─ export/gist · pr comments · ci/status · tests/suggest   │
│   ├─ projects (CRUD) · audit · admin/audit · admin/policies  │
│   └─ metrics (Prometheus)                                    │
│  utils/coder/                                                │
│   ├─ github_client.py  — REST GitHub/GHES, retry-политики    │
│   ├─ changeset.py      — валидация путей/лимитов, diff       │
│   ├─ policy.py         — админ-политики (allow/block-листы)  │
│   ├─ semantic.py       — семантический поиск (эмбеддинги +   │
│   │                      lexical fallback, кэш эмбеддингов)  │
│   ├─ export_worker.py  — асинхронный экспорт (asyncio task)  │
│   └─ metrics.py        — prometheus-счётчики coder_*         │
│  models/coder.py       — SQLAlchemy-модели + Pydantic-схемы  │
│  migrations/versions/  — Alembic (4 ревизии coder_*)         │
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

### 2.6. Общие соглашения

- Ошибки: `{"detail": "...", "code": "..."}`; код `CODER_AUTH_*` — проблемы
  подключения/токена, `RATE_LIMITED` — превышение лимита запросов к файлам.
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
  `audit_cleanup`.

## 3. Схема данных и миграции

Таблицы (Alembic, применяются автоматически при старте):

| Таблица | Назначение | Ключи/индексы |
|---|---|---|
| `coder_github_connection` | Шифрованные OAuth-токены; несколько аккаунтов на пользователя | PK `id`; уникальность `(user_id, github_host)`; `is_default` |
| `coder_project` | Сохраняемые проекты (owner/repo/default_branch/meta) | PK `id`; `uq_coder_project_user_repo` |
| `coder_export_job` | Задачи экспорта со снапшотом Change Set и статусом | PK `id`; `idempotency_key` unique; индексы user/status |
| `coder_audit_event` | Журнал аудита (action/target/payload без секретов, correlation_id, ip_address, user_agent) | PK `id`; индексы user/created_at |

Ревизии:

1. `c0d3r4b17e21` — создание четырёх таблиц MVP.
2. `c0d3r4ud1t01` — поля контекста аудита `correlation_id`, `ip_address`, `user_agent` (§11.4).
3. `c0d3r4m1c7h1` — мульти-GitHub: колонки `github_host`, `is_default`,
   backfill существующих строк (`github.com`, default), замена уникальности
   `user_id` на `(user_id, github_host)`. Реализовано через
   `batch_alter_table` — совместимо с SQLite и PostgreSQL.

Downgrade миграции 3 схлопывает несколько подключений в одно перед
восстановлением старой уникальности (см. файл миграции).

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
8. **Аудит.** Личный журнал действий — Environment → Audit.

## 6. Настройка GitHub App / OAuth

Раздел использует **GitHub OAuth App** (не GitHub App):

1. GitHub → Settings → Developer settings → OAuth Apps → New OAuth App.
2. **Authorization callback URL:**
   `{BASE_URL}/api/v1/coder/github/auth/callback`
   (локально по умолчанию `http://localhost:8083/api/v1/coder/github/auth/callback`).
3. Скопируйте Client ID/Secret в `.env`, перезапустите контейнер.
4. Требуемые scope OAuth приложения: `repo` (чтение/запись контента),
   `gist`, `read:org` (опционально для allow-list orgs).
5. **GitHub Enterprise Server:** установите OAuth-приложение на самом
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
| `403 feature disabled` | `CODER_ENABLED=false` или контейнер не перезапущен после правки `.env` | Включить флаг, перезапустить |
| «host not allowed» (`permission_denied`) | Домен не входит в `CODER_ALLOWED_GITHUB_HOSTS` | Добавить домен GHES в переменную |
| Protected branch / запись в main отказана | Это ожидаемое поведение: экспорт всегда идёт в новую ветку + PR | Открыть PR на ревью |
| `RATE_LIMITED` | Превышен лимит обращений к файлам за сессию | Повторить позже; использовать `repo_search` вместо массового чтения |
| Экспорт завис в `running` | Фоновая задача упала при рестарте процесса | Открыть job повторно (`/export/jobs/{id}`), при необходимости запустить экспорт заново — `idempotency_key` защитит от дублей |
| Таблицы `coder_*` отсутствуют | Миграции не применены | `alembic upgrade head` в окружении бэкенда (миграция `c0d3r4m1c7h1` обязательна для мульти-подключений) |
| Токены нечитаемы после смены key | Rotation `CODER_ENCRYPTION_KEY` | Переподключить GitHub (§4.3) |

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

- **Что бэкапить:** каталог `data/` (SQLite `webui.db` + загруженные файлы)
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

Дополнительно: статические проверки изменённых модулей (`py_compile`,
flake8) и компиляция Svelte-компонентов (`svelte.compile`) — без ошибок.

Ограничение: полный OAuth-поток до реального GitHub требует
зарегистрированных аккредитов; E2E проверяет только редирект.

## 10. Известные ограничения

1. Авторизация — только GitHub OAuth (GitHub App не поддерживается); PAT-ввод не предусмотрен.
2. Асинхронный экспорт выполнен на asyncio-задачах внутри процесса: при жёстком рестарте сервера незавершённый job останется в статусе `running` и требует повторного запуска (идемпотентность защищает от дублей).
3. Семантический поиск деградирует до lexical-ранжирования, если эмбеддинг-эндпоинт недоступен; кэш эмбеддингов — in-process (не разделяется между репликами).
4. Поддержка GHES ограничена REST API v3 (`https://<host>/api/v3`); webhooks/GitHub App flows вне объёма.
5. Rate limiting файлов — мягкий (счётчик на пользователя/сессию), без распределённого state.
6. Retention-очистка аудита выполняется по запросу (админ/UI или cron), не фоновым планировщиком.
7. Экспорт в Gist не участвует в политиках allow-list репозиториев (Gist вне репозиторной модели).
8. Метрики Prometheus раскрываются эндпоинтом, доступным только admins; pull-скрапер Grafana/Prometheus на стороне оператора.
