# ToDo — открытые задачи

> Обновляется после каждой завершённой задачи. Полный список переменных и
> инструкции — в README.md (раздел «Работа с Coder»).

## Coder-секция — доработки по ТЗ (Coder.md)

Сверка реализации с тех. заданием (см. `Coder.md`). МVP-объём реализован;
ниже — незакрытые пункты. Приоритет: 1 → 2 → 3.

### Приоритет 1 — тесты (Этап 11, §19, AC-16, NFR-09)

- [ ] Unit-тесты: валидация путей, валидация Change Set, шифрование/расшифровка
      токенов, генерация diff, обработка ошибок GitHub API, идемпотентность.
- [ ] Integration-тесты (mock GitHub): OAuth callback, repo/tree/file,
      blob→tree→commit→ref, PR, отзыв токена, protected branch, rate limit.
- [ ] E2E-тесты основных сценариев (соединить → выбрать repo → файл → Change Set
      → diff → экспорт → PR → ссылки → отключить).
- [ ] Security-тесты: path traversal, IDOR, CSRF, XSS, token leakage,
      unauthorized export, replay, resource consumption.

### Приоритет 2 — админ-политики (Этап 9, §15.1)

- [ ] Разрешённые GitHub hosts / orgs / repos.
- [ ] Запрещённые пути / блок-лист (`.env`, `*.pem`, `secrets/*`, `.git/*`).
- [ ] Настройки обязательного PR и лимитов через административный слой.
- [ ] Retry-политика и таймауты GitHub API как настройки (сейчас зашиты в
      `github_client.py`).
- [ ] Retention аудит-лога.

### Приоритет 3 — надёжность и наблюдаемость

- [ ] Асинхронный экспорт (NFR-08): вынести Git Data API из HTTP-запроса
      (`/export/start` сейчас синхронный) в фоновый воркер/очередь.
- [ ] Correlation ID (14.3) + поля аудита `correlation_id`/`ip_address`/
      `user_agent` в `CoderAuditEvent` (§11.4).
- [ ] Расширить события аудита (§14.1): section_accessed, repo_selected,
      file_viewed, diff_generated, permission_denied, rate_limited и др.
- [ ] Metrics (14.2): prometheus-счётчики coder_*.
- [ ] Админский обзор аудита по всем пользователям (сейчас `/audit` — только
      события текущего пользователя).

### Вторая очередь (§22.2) / мелочи

- [x] Secret scanning (§13.5): детекция AWS-ключей, private keys, GitHub/Slack
      токенов, JWT, паролей, entropy; режимы warn/block/off.
- [x] Сохраняемые проекты и шаблоны (сейчас `coder_project` создаётся только
      при открытии дерева, UI списка проектов нет).
- [ ] Semantic search по репозиторию.
- [ ] Автогенерация тестов / CI-статусы.
- [ ] Review comments в PR.
- [ ] Несколько GitHub-подключений.
- [ ] Экспорт в Gist.
- [ ] Документация §20: описание API, схема данных, руководство администратора,
      руководство пользователя, backup/recovery, отчёт о тестировании, список
      известных ограничений.
- [ ] Поддержка `rename` в Change Set (§8.3).
- [ ] Сверка лимитов с §13.4: код даёт 20 файлов / 3 МиБ, ТЗ — 50 / 5 МиБ.

## Coder-секция — запуск в работу

- [x] **Вписать реальные OAuth-креды** в `.env`: `CODER_GITHUB_CLIENT_ID` и
      `CODER_GITHUB_CLIENT_SECRET` от созданного OAuth-приложения GitHub
      (Settings → Developer settings → OAuth Apps). Callback URL:
      `http://<host>:8083/api/v1/coder/github/auth/callback`.
- [x] **Перезапустить контейнер** после правки `.env`, чтобы приложение
      подхватило переменные и применило Alembic-миграцию (`coder_*` таблицы).
- [ ] **Проверить подключение GitHub** в разделе Coder (кнопка
      «Подключить GitHub» → редирект на OAuth → возврат с установленным
      соединением).

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

Дата обновления: 2026-10-24
Комментарии: Список расширен анализами кода и новых возможностей. Обновлено: реализованы авто-улучшение запросов, мульти-стратегия поиска, контекстное переупорядочивание, кеширование RAG, интерактивная оценка качества RAG, XLSX со всеми листами, поддержка xls/rtf/doc, дедупликация по пути и metadata.
