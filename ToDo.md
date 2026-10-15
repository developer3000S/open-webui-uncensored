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

- [ ] Secret scanning (§13.5): детекция AWS-ключей, private keys, GitHub/Slack
      токенов, JWT, паролей, entropy; режимы warn/block/off.
- [ ] Сохраняемые проекты и шаблоны (сейчас `coder_project` создаётся только
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

- [ ] **Вписать реальные OAuth-креды** в `.env`: `CODER_GITHUB_CLIENT_ID` и
      `CODER_GITHUB_CLIENT_SECRET` от созданного OAuth-приложения GitHub
      (Settings → Developer settings → OAuth Apps). Callback URL:
      `http://<host>:8083/api/v1/coder/github/auth/callback`.
- [ ] **Перезапустить контейнер** после правки `.env`, чтобы приложение
      подхватило переменные и применило Alembic-миграцию (`coder_*` таблицы).
- [ ] **Проверить подключение GitHub** в разделе Coder (кнопка
      «Подключить GitHub» → редирект на OAuth → возврат с установленным
      соединением).

Сделано ранее:
- [x] `CODER_ENCRYPTION_KEY` сгенерирован и вписан в `.env`.
- [x] `.env` очищен от нечитаемых кодом Coder-переменных (см. Warning в README).
- [x] Сверка реализации с ТЗ `Coder.md` (этот файл).
