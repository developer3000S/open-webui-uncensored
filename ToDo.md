# ToDo — открытые задачи

> Обновляется после каждой завершённой задачи. Полный список переменных и
> инструкции — в README.md (раздел «Работа с Coder»).

## Coder-секция — доработки по ТЗ (Coder.md)

Сверка реализации с тех. заданием (см. `Coder.md`). МVP-объём реализован;
ниже — незакрытые пункты. Приоритет: 1 → 2 → 3.

### Приоритет 1 — тесты (Этап 11, §19, AC-16, NFR-09)

- [x] Unit-тесты: валидация путей, валидация Change Set, шифрование/расшифровка
      токенов, генерация diff, обработка ошибок GitHub API, идемпотентность.
- [x] Integration-тесты (mock GitHub): OAuth callback, repo/tree/file,
      blob→tree→commit→ref, PR, отзыв токена, protected branch, rate limit.
- [x] E2E-тесты (headless Firefox): загрузка `/coder`, кнопка "Connect GitHub" →
      github.com OAuth, `/api/v1/coder/config`. Полный поток подключения GitHub
      требует реальных OAuth-аккредитов. Проговорено: запуск тестов требует контейнера
      с `CODER_ENABLED=true` и тестового пользователя `e2e@test.local`.
- [x] Security-тесты: path traversal, IDOR, CSRF, XSS, token leakage,
      unauthorized export, replay, resource consumption.

### Приоритет 2 — админ-политики (Этап 9, §15.1)

- [x] Разрешённые GitHub hosts / orgs / repos (`CODER_ALLOWED_GITHUB_HOSTS`,
      `CODER_ALLOWED_ORGS`, `CODER_ALLOWED_REPOS`; проверка в `utils/coder/policy.py`,
      обзор — `GET /api/v1/coder/admin/policies`).
- [x] Запрещённые пути / блок-лист (`.env`, `*.pem`, `secrets/*`, `.git/*`) —
      `CODER_BLOCKED_PATHS`.
- [x] Настройки обязательного PR и лимитов через административный слой
      (`CODER_REQUIRE_PR`, `CODER_MAX_*`).
- [x] Retry-политика и таймауты GitHub API как настройки
      (`CODER_GITHUB_RETRY_POLICY`/`_MAX`/`_DELAY`, `CODER_GITHUB_TIMEOUT`).
- [x] Retention аудит-лога (`CODER_AUDIT_RETENTION_DAYS` + `POST /audit/cleanup`).

### Приоритет 3 — надёжность и наблюдаемость

- [x] Асинхронный экспорт (NFR-08): `/export/start` регистрирует job и исполняет
      его фоново (`utils/coder/export_worker.py`, `CODER_ASYNC_EXPORT`); статус —
      `GET /export/jobs/{id}`.
- [x] Correlation ID (14.3) + поля аудита `correlation_id`/`ip_address`/
      `user_agent` в `CoderAuditEvent` (§11.4, миграция `c0d3r4ud1t01`).
- [x] Расширены события аудита (§14.1): section_accessed, repo_selected,
      file_viewed, permission_denied, rate_limited, semantic_search,
      review_comment_created, ci_status_viewed, gist_exported, test_issue_created,
      project_created/deleted, github_connection_* и др.
- [x] Metrics (14.2): prometheus-счётчики coder_* (`utils/coder/metrics.py`,
      `GET /api/v1/coder/metrics`).
- [x] Админский обзор аудита по всем пользователям: `GET /api/v1/coder/admin/audit`
      + секция Audit во вкладке Environment.

### Вторая очередь (§22.2) / мелочи

- [x] Secret scanning (§13.5): детекция AWS-ключей, private keys, GitHub/Slack
      токенов, JWT, паролей, entropy; режимы warn/block/off.
- [x] Сохраняемые проекты и шаблоны (сейчас `coder_project` создаётся только
      при открытии дерева, UI списка проектов нет).
- [x] Semantic search по репозиторию (`utils/coder/semantic.py`,
      `GET /search/semantic`; эмбеддинги с lexical fallback и кэшем).
- [x] Автогенерация тестов (`POST /tests/suggest` + issue в репозитории) /
      CI-статусы (`GET /ci/status`).
- [x] Review comments в PR (`GET|POST /pr/{owner}/{repo}/{n}/comments`).
- [x] Несколько GitHub-подключений (+GHES): модель `github_host`/`is_default`,
      миграция `c0d3r4m1c7h1`, эндпоинты `/github/connections*`, UI-панель
      «GitHub accounts» во вкладке Environment.
- [x] Экспорт в Gist (`POST /export/gist`, кнопка в ExportDialog).
- [x] Документация §20: полный комплект — `docs/CODER.md` (архитектура, API,
      схема данных и миграции, руководство администратора, руководство
      пользователя, настройка OAuth/GHES, runbook, backup/recovery, отчёт о
      тестировании, известные ограничения); README/TROUBLESHOOTING обновлены.
- [x] Поддержка `rename` в Change Set (§8.3).
- [x] Сверка лимитов с §13.4: подняты до 50 файлов / 5 МиБ суммарно
      (`CODER_MAX_FILES_PER_CHANGESET=50`, `CODER_MAX_TOTAL_DIFF_SIZE=5MiB`).

## Coder-секция — запуск в работу

- [x] **Вписать реальные OAuth-креды** в `.env`: `CODER_GITHUB_CLIENT_ID` и
      `CODER_GITHUB_CLIENT_SECRET` от созданного OAuth-приложения GitHub
      (Settings → Developer settings → OAuth Apps). Callback URL:
      `http://<host>:8083/api/v1/coder/github/auth/callback`.
- [x] **Перезапустить контейнер** после правки `.env`, чтобы приложение
      подхватило переменные и применило Alembic-миграцию (`coder_*` таблицы).
- [x] **Проверить подключение GitHub** в разделе Coder (кнопка
      «Подключить GitHub» → редирект на OAuth → возврат с установленным
      соединением). Ручная проверка проведена — успешно (2026-10-27);
      автоматизированная часть проверена E2E (редирект на github.com) — см. docs/CODER.md §9.

Сделано ранее:
- [x] `CODER_ENCRYPTION_KEY` сгенерирован и вписан в `.env`.
- [x] `.env` очищен от нечитаемых кодом Coder-переменных (см. Warning в README).
- [x] Сверка реализации с ТЗ `Coder.md` (этот файл).

## Coder — план развития по мотивам coder.qwen.ai (анализ 2026-10-27)

Продукт Qwen Coder (главная страница и страница задачи `/c/<uuid>` — SPA на
React; анализ выполнен по HTML и бандлу `qwen-coder-fe/0.0.29/js/main.js`:
API-маршруты, названия состояний, тексты кнопок и шаблоны). Ключевое отличие от
нашей реализации: Qwen Coder строит приложения в **изолированном sandbox** с
живым превью и публикацией, а не только редактирует файлы GitHub-репозитория.
Ниже — gap-анализ и план; приоритеты: A → B → C → D.

### A. Sandbox-окружение и живой Preview (ключевое отличие)

- [x] **Изолированный sandbox для задач**: файловая песочница на задачу
      (`utils/coder/sandbox.py`, `POST /api/v1/coder/sandbox/session`),
      жизненный цикл create/pause/resume/destroy, таблица `coder_sandbox_session`
      (миграция `c0d3r45ndb0x`), лимиты `CODER_SANDBOX_MAX_*` + TTL
      `CODER_SANDBOX_TTL_MINUTES` с админским sweep (`POST /sandbox/sweep`).
      MVP выполнен как изолированный FS-root без контейнерного рантайма
      (выполнение кода в песочнице не предусмотрено — см. docs/CODER.md §10.9).
- [x] **iframe-превью**: панель «Preview» в Workspace; живой рендер статики
      через `GET /sandbox/session/{id}/preview?v=` (cache-buster = hot-reload),
      кнопка refresh; публикация работает через тот же iframe-механизм.
- [x] **Редактор кода в браузере**: эндпоинты read/write/delete файлов
      песочницы (`GET|PUT|DELETE /sandbox/session/{id}/file`) + UI-редактор
      во вкладке Workspace; поиск по файлам проекта — через семантический/
      grep-поиск репозитория и список файлов сессии.
- [x] **Публикация одним кликом**: `POST /sandbox/session/{id}/publish` →
      копия в `DATA_DIR/published/<share_id>`, публичная страница
      `/api/v1/coder/preview/s/{share_id}` (без авторизации, аналог `/s/<id>`
      у Qwen); повторный вызов = redeploy. Кастомный поддомен — на уровне
      reverse-proxy оператора.
- [x] **Остановка генерации**: кнопка Stop обрывает LLM-стрим
      (`streamController.abort()`); применённые к песочнице файлы остаются,
      неприменённая часть Change Set откатывается (не применяется).

### B. Режимы и шаблоны генерации

- [x] **Пресеты типов проектов**: Web Dev / Data Visualization / Visual Design /
      Prototype (`utils/coder/modes.py`, `GET /api/v1/coder/modes`) — каждый со
      своим системным промптом и стартовым скелетом файлов.
- [x] **Библиотека готовых шаблонов-стартов**: карточки «Build a Snake Game»,
      «Create a Pomodoro Timer», «Build a Coffee Shop», «Create a Solar System
      Demo» — галерея из `GET /modes` (поле `templates`), старт sandbox-сессии
      с `template_id`.
- [x] **Автосохранение названий и тегов задач**: `POST /tasks/{chat_id}/title`
      (эвристическая быстрая генерация title/tags без лишнего LLM-вызова;
      ручное переопределение — `POST /tasks/{chat_id}`).
- [x] **Follow-up предложения после ответа модели**: чипы «что сделать дальше»
      (`GET /tasks/{chat_id}/followups?mode=`) под последним сообщением чата.

### C. Управление задачами и проектами

- [x] **Архив и закрепление задач**: pin/unpin, archive/restore, просмотр
      архива (`is_pinned`/`is_archived` в `coder_task_meta`,
      `GET /tasks?archived=`, `POST /tasks/{chat_id}`).
- [x] **Глобальный поиск по задачам** + фильтры: `GET /tasks?q=&tag=`
      (поиск по title/tags, фильтр по тегу; сортировка pinned-first).
- [x] **Состояния задач в списке**: status running/done/error с индикатором
      (обновляется при старте/завершении генерации).
- [x] **Публичный шеринг и fork задач** (2026-10-28): `coder_task_meta.share_id/share_enabled`
      (+миграция Alembic), эндпоинты `POST /tasks/{chat_id}/share` (вкл/выкл, идемпотентный
      токен), `GET /tasks/shared/{token}` (публичная страница меты задачи с html.escape —
      защита от XSS) и `POST /tasks/shared/{token}/fork` — копирует sandbox-сессию именно
      расшаренной задачи (привязка `coder_sandbox_session.chat_id` + миграция) в новую задачу
      форкера через `copy_sandbox` (лимиты квоты сохраняются). UI: кнопка «Share publicly»
      под полем ввода с копированием ссылки и отзывом, обработка `/coder?fork=<token>`.
      Тесты: `backend/tests/test_coder_share_fork.py` — 16 passed (токены, отзыв, IDOR,
      XSS, копирование файлов, интеграционный fork-flow).
- [ ] **Импорт/экспорт истории**: загрузка чатов/проектов (`/chats/import`) и
      выгрузка Change Set в zip без GitHub — не реализовано (частично закрыто
      экспортом в Gist).

### D. Подключение репозиториев и аккаунтов

- [ ] **Установка GitHub App вместо OAuth-токена пользователя** (`/github/install/url`):
      доступ сразу ко всем репозиториям организации с гранular-правами; хранить
      installation-токены, refresh по TTL.
- [ ] **Выбор организаций при подключении** (`/github/organizations`) — фильтр
      списка репозиториев по org.
- [ ] **Проверка валидности соединения** (`/github/connection_status` + `/github/validate`):
      фоновая проверка срока жизни токена/scopes с предупреждением в UI Environment.
- [ ] **Вход через Google и email OTP** (`/auths/google_oauth`, `/auths/otp/email/*`) —
      для внешнего multi-user деплоя Coder.

### E. Наблюдаемость генерации (UX во время работы агента)

- [ ] **Стрим стадий «Thinking → Planning → Coding → Verifying»** с таймингами и
      сворачиваемыми блоками инструментов (файлы/команды), как `thinking_summary` у Qwen.
- [x] **Метрики стрима в аудите**: first packet time и число чанков —
      `POST /api/v1/coder/stream/metrics` → Prometheus-гистограммы
      `coder_stream_first_chunk_seconds`/`coder_stream_chunks_total`
      (`utils/coder/metrics.py::observe_stream`) + событие аудита
      `generation_streamed`; UI замеряет стрим и отправляет метрики.
- [x] **Прогресс-бар/таймер долгих операций**: статус export jobs обновляется
      асинхронно в панели Jobs; sandbox/publish операции показывают busy-состояние
      и toast-прогресс поверх чата.

### Итог

Приоритеты **A, B, C (кроме импорта истории) и E (метрики стрима) реализованы**
(2026-10-27; fork/шеринг задач закрыт 2026-10-28): sandbox+preview+publish, режимы/шаблоны,
управление задачами, публичный share+fork,
stream-metrics — документация синхронизирована (docs/CODER.md §1–§10, README
«Работа с Coder» §3.1, TROUBLESHOOTING, CHANGELOG). Остались: D (GitHub App,
валидация соединения, Google/OTP), C-импорт истории, E-стрим стадий
агента. Дата обновления: 2026-10-28.

## RAG и обработка знаний

- [x] **Улучшение дедупликации**: Дедупликация по полному пути и metadata, не только хеш текста.
- [x] **Авто-улучшение запросов**: LLM-переформулировка вопросов пользователя для лучших методов поиска.
- [x] **Мульти-стратегия поиска**: Фьюзинг векторного, BM25 и графового поиска.
- [x] **Контекстное переупорядочивание**: Пересчёт ранжирования на основе истории диалога.
- [x] **Интерактивная оценка качества RAG**: Кнопки "thumbs up/down" для обучения ранжировщика.
- [x] **Кеширование результатов поиска**: Персистентное RAG-cache с invalidation при изменении документа.
- [x] **XLSX — все листы**: Загрузка всех листов xlsx-файла, а не только первого (через `ExcelLoader`).
- [x] **Поддержка xls, rtf, doc**: Загрузка файлов этих форматов (fallback на `SimpleTextLoader`, `TextLoader`, `docx2txt`, `pypandoc`).

## Мониторинг и наблюдаемость

- [ ] **OpenTelemetry автоматизация**: Простое подключение к OTEL collector.
- [ ] **Расширенные метрики**: CPU, memory, GPU, token usage per model/request.
- [ ] **Динамическое rate limiting**: Автоматическое ограничение при перегрузке.
- [ ] **Webhook events**: Подписка на события для внешних интеграций.
- [ ] **Dashboard login audit**: Real-time визуализация попыток входа и аномалий.
- [ ] **Centralized logging**: Интеграция с ELK, Loki, Splunk.

## Безопасность

- [ ] **A/B тестирование моделей**: Управление группами пользователей и роутингом.
- [ ] **DLP (Data Loss Prevention)**: Выезд моделей для предотвращения утечек.
- [ ] **Аудит доступа к файлам**: Логирование всех операций с файлами.
- [ ] **Мультитенантная изоляция**: Полное разделение данных между tenants.
- [ ] **Шифрование at rest**: Включая историю чатов и базы знаний.
- [ ] **Secret management**: Интеграция с HashiCorp Vault, AWS Secrets Manager.

## Производительность и масштабирование

- [ ] **Distributed processing**: Распределение задач через Redis/RabbitMQ.
- [ ] **Task queue improvements**: Приоритеты, sequencing, retry policies.
- [ ] **Database sharding**: Горизонтальное масштабирование БД.
- [ ] **Кэширование**: Redis/Memcached для запросов, результатов, in-memory.
- [ ] **GPU scheduling**: Автоматическое распределение GPU задач.
- [ ] **Compression**: Компрессия данных при передаче и хранении.

## UI/UX улучшения

- [ ] **Тёма по системе**: Автоматическое переключение light/dark в зависимости от OS.
- [ ] **Mobile-first redesign**: Полная адаптация под мобильные устройства.
- [ ] **Accessibility compliance**: WCAG 2.1 AA утверждена.
- [ ] **Пользовательские темы**: Создание тем через визуальный редактор.
- [ ] **Keyboard shortcuts**: Расширенная поддержка клавеатур.
- [ ] **Real-time collaboration**: Совместное редактирование чатов.

## Экстенсибилити и плагины

- [ ] **Plugin marketplace**: Маркетплейс плагинов с версионированием.
- [ ] **Custom actions**: Actions на TypeScript/JS/Python.
- [ ] **API extensions**: Точки расширения для новых API endpoints.
- [ ] **Webhooks for events**: Пользовательские вебхуки.
- [ ] **Structured data endpoints**: REST/GraphQL для внешних систем.
- [ ] **CLI tooling**: CLI для управления проектом.

## Администрирование

- [ ] **Role-based dashboard**: Персонализированные дашборды.
- [ ] **Usage reports**: Расчёт стоимости, потребления, backup restore.
- [ ] **Health checks**: Проверка серверов, БД, внешних сервисов.
- [ ] **Version control for configs**: Версионирование конфигов с rollback.
- [ ] **Automated backup**: Автоматические бэкапы БД и файлов.
- [ ] **Multi-region deployment**: Множественные регионы.

## Интеграции

- [ ] **Slack/Teams integration**: Подключение к мессенджерам.
- [ ] **Calendar sync**: Интеграция с Google Calendar, Outlook.
- [ ] **Cloud storage**: Deep integration с Google Drive, OneDrive, Dropbox.
- [ ] **Code repositories**: GitLab, Bitbucket, Azure DevOps.
- [ ] **CI/CD integration**: GitHub Actions, GitLab CI, Jenkins.
- [ ] **Documentation generators**: Автогенерация документации из чатов.

## Тестирование

- [ ] **Integration tests for API**: API интеграционные тесты.
- [ ] **E2E для критических сценариев**: Coder, file upload, chat.
- [ ] **Performance benchmarks**: Автоматические бенчмарки.
- [ ] **Security scanning**: Автоматический security scanning кода.
- [ ] **Chaos engineering**: Тесты устойчивости при сбоях.

---

Дата обновления: 2026-10-27
Комментарии: Все пункты плана Coder (приоритеты 1–3 и вторая очередь, включая документацию §20) реализованы; ручная проверка OAuth-подключения GitHub — успешно. Добавлен новый план развития Coder по мотивам анализа coder.qwen.ai (раздел «Coder — план развития по мотивам coder.qwen.ai»: sandbox+preview, режимы/шаблоны генерации, управление задачами, GitHub App, наблюдаемость генерации). Список расширен анализами кода и новых возможностей. Обновлено: реализованы авто-улучшение запросов, мульти-стратегия поиска, контекстное переупорядочивание, кеширование RAG, интерактивная оценка качества RAG, XLSX со всеми листами, поддержка xls/rtf/doc, дедупликация по пути и metadata. Завершено Comprehensive тестирование Coder: unit, integration, security-тесты (59+8+14=81 тестов) и написано E2E. Реализованы приоритеты A/B/C/E плана coder.qwen.ai: sandbox+живой preview+публикация (`utils/coder/sandbox.py`, миграция `c0d3r45ndb0x`), режимы и шаблоны генерации (`utils/coder/modes.py`), управление задачами (pin/archive/поиск/title/followups, `coder_task_meta`), метрики стрима (`POST /stream/metrics`). Документация синхронизирована: docs/CODER.md v2.1 (API §2.7–§2.10, схема данных, переменные CODER_SANDBOX_*/CODER_PUBLISH_*, runbook, ограничения 9–13), README («Работа с Coder» §3.1 + таблицы env), TROUBLESHOOTING (sandbox/preview/publish), CHANGELOG. Дата: 2026-10-27.
## Enhancements from open-webui/computer

### AI & Agent Improvements
- [ ] **Advanced AI Agent Frameworks**: Integration of state-of-the-art AI agent adaptors (OpenCode V2, ACP-compatible).
- [ ] **Anthropic Capabilities**: Fix silent caps on `max_tokens`, improve handling of refusals.
- [ ] **LaTeX Math Rendering**: Full Markdown-LaTeX math rendering in chat interface.
- [ ] **Agent Image Visibility**: Agents can see images; `display_file` provides full path and base64.
- [ ] **Auto-Compaction**: Run compaction even when all input tokens are shown; mid-agent-run compaction.

### System & Configuration
- [ ] **Configurable Search Providers**: API URL configuration for search providers.
- [ ] **Model Prefix Setting**: UI to set model prefixes for discovery.
- [ ] **save_config() Improvements**: Proper newline escape to prevent invalid config.toml loss.
- [ ] **Strict Jinja Template Handling**: Graceful handling of missing user-role messages.

### Git & Repositories
- [ ] **Multiple Git Repositories**: Support for managing multiple Git repos in one workspace.
- [ ] **Workspace Command Permissions**: Better control of CLI commands from agents.
- [ ] **Git Identity Validation**: Smarter handling of author identity (email, username).

### UI/UX
- [ ] **Formatted Responses Copying**: Community userscript for improved copying.
- [ ] **Shift-to-Delete Old Chats**: Quick deletion of old chats by holding shift.
- [ ] **Git Bar Commit Indicators**: Visual feedback for commit errors.
- [ ] **Cost Monitoring Dashboard**: Track usage costs per agent/chat/model.
- [ ] **Background Commands Management**: UI to view/kill running background commands.

### Utilities & Resilience
- [ ] **Utility Tasks Timeout Resilience**: Adjustable timeout for utility tasks on slow hardware.
- [ ] **Partial Prompt Caching**: Keep context across calls, compaction tuning.
- [ ] **API Expiry and Saturation**: Optimize prompts, reduce token waste.
- [ ] **Websocket Enhancements**: Better connectivity for real-time tasks.

> **Why**: open-webui/computer contains cutting-edge features and fixes that improve agent performance, UI/UX, configuration robustness, and monitoring.
> **How to apply**: Review each feature, prioritize, implement and test in this Open WebUI instance, update documentation.

**Дата анализа и интеграции в план: 2026-10-28**
