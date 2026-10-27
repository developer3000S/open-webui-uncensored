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
- [ ] **Проверить подключение GitHub** в разделе Coder (кнопка
      «Подключить GitHub» → редирект на OAuth → возврат с установленным
      соединением). Требует реальных аккредитов OAuth-приложения; автоматизированная
      часть проверена E2E (редирект на github.com) — см. docs/CODER.md §9.

Сделано ранее:
- [x] `CODER_ENCRYPTION_KEY` сгенерирован и вписан в `.env`.
- [x] `.env` очищен от нечитаемых кодом Coder-переменных (см. Warning в README).
- [x] Сверка реализации с ТЗ `Coder.md` (этот файл).

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
Комментарии: Все пункты плана Coder (приоритеты 1–3 и вторая очередь, включая документацию §20) реализованы; документация — в `docs/CODER.md`. Отмечены также исправления компиляции `+page.svelte` и импорта роутера `routers/coder.py` (ошибка «Unexpected token '<'»). Список расширен анализами кода и новых возможностей. Обновлено: реализованы авто-улучшение запросов, мульти-стратегия поиска, контекстное переупорядочивание, кеширование RAG, интерактивная оценка качества RAG, XLSX со всеми листами, поддержка xls/rtf/doc, дедупликация по пути и metadata. ЗавершеноComprehensive тестирование Coder: unit, integration, security-тесты (59+8+14=81 тестов) и написано E2E.
