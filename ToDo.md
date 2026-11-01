# ToDo — открытые задачи

> Обновляется после каждой завершённой задачи. Полный список переменных и инструкции — в README.md (раздел «Работа с Coder»).

## Общие задачи

### Исправления и обновления

- [x] **Удалены зависимости Tailwind CSS**: Устранены ошибки сборки, связанные с Tailwind CSS, и заменены на стандартные CSS классы.
- [x] **Обновлены стили**: Все классы Tailwind CSS (`rounded-lg`, `prose-*`, `bg-*`, `text-*` и др.) заменены на стандартные CSS стили.
- [x] **Восстановлен `.gitignore`**: Обновлён и восстановлен `.gitignore` для корректного исключения файлов и директорий из контроля версий.

## Coder-секция — доработки по ТЗ (Coder.md)

Сверка реализации с тех. заданием (см. `Coder.md`). MVP-объём реализован;
ниже — незакрытые пункты. Приоритет: 1 → 2 → 3.

### Приоритет 1 — тесты (Этап 11, §19, AC-16, NFR-09)

- [x] Unit-тесты: валидация путей, валидация Change Set, шифрование/расшифровка токенов, генерация diff, обработка ошибок GitHub API, идемпотентность.
- [x] Integration-тесты (mock GitHub): OAuth callback, repo/tree/file, blob→tree→commit→ref, PR, отзыв токена, protected branch, rate limit.
- [x] E2E-тесты (headless Firefox): загрузка `/coder`, кнопка "Connect GitHub" → github.com OAuth, `/api/v1/coder/config`. Полный поток подключения GitHub требует реальных OAuth-аккредитов. Проговорено: запуск тестов требует контейнера с `CODER_ENABLED=true` и тестового пользователя `e2e@test.local`.
- [x] Security-тесты: path traversal, IDOR, CSRF, XSS, token leakage, unauthorized export, replay, resource consumption.

### Приоритет 2 — админ-политики (Этап 9, §15.1)

- [x] Разрешённые GitHub hosts / orgs / repos (`CODER_ALLOWED_GITHUB_HOSTS`, `CODER_ALLOWED_ORGS`, `CODER_ALLOWED_REPOS`; проверка в `utils/coder/policy.py`, обзор — `GET /api/v1/coder/admin/policies`).
- [x] Запрещённые пути / блок-лист (`.env`, `*.pem`, `secrets/*`, `.git/*`) — `CODER_BLOCKED_PATHS`.
- [x] Настройки обязательного PR и лимитов через административный слой (`CODER_REQUIRE_PR`, `CODER_MAX_*`).
- [x] Retry-политика и таймауты GitHub API как настройки (`CODER_GITHUB_RETRY_POLICY`/`_MAX`/`_DELAY`, `CODER_GITHUB_TIMEOUT`).
- [x] Retention аудит-лога (`CODER_AUDIT_RETENTION_DAYS` + `POST /audit/cleanup`).

### Приоритет 3 — надёжность и наблюдаемость

- [x] Асинхронный экспорт (NFR-08): `/export/start` регистрирует job и исполняет его фоново (`utils/coder/export_worker.py`, `CODER_ASYNC_EXPORT`); статус — `GET /export/jobs/{id}`.
- [x] Correlation ID (14.3) + поля аудита `correlation_id`/`ip_address`/`user_agent` в `CoderAuditEvent` (§11.4, миграция `c0d3r4ud1t01`).
- [x] Расширены события аудита (§14.1): section_accessed, repo_selected, file_viewed, permission_denied, rate_limited, semantic_search, review_comment_created, ci_status_viewed, gist_exported, test_issue_created, project_created/deleted, github_connection_* и др.
- [x] Metrics (14.2): prometheus-счётчики coder_* (`utils/coder/metrics.py`, `GET /api/v1/coder/metrics`).
- [x] Админский обзор аудита по всем пользователям: `GET /api/v1/coder/admin/audit`.

## Задачи на будущее

- [ ] Реализация новых функций и улучшений интерфейса.
- [ ] Оптимизация производительности.
- [ ] Документация новых функций.

## Документация

Для получения дополнительной информации о настройке и использовании Open WebUI, пожалуйста, ознакомьтесь с [документацией](https://docs.openwebui.com/).