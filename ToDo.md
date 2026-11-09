# ToDo — открытые задачи

> Обновляется после каждой завершённой задачи. Полный список переменных и инструкции — в README.md (раздел «Работа с Coder»).

## Общие задачи

### Исправления и обновления

- [x] **Исправлена ошибка `.subscribe`**: Устранена ошибка `TypeError: e.subscribe is not a function` в SettingsModal.svelte и +layout.svelte путём замены устаревших вызовов `.subscribe()` на реактивные блоки Svelte 5.
- [x] **Удалены зависимости Tailwind CSS**: Устранены ошибки сборки, связанные с Tailwind CSS, и заменены на стандартные CSS классы.
- [x] **Обновлены стили**: Все классы Tailwind CSS (`rounded-lg`, `prose-*`, `bg-*`, `text-*` и др.) заменены на стандартные CSS стили.
- [x] **Восстановлен `.gitignore`**: Обновлён и восстановлен `.gitignore` для корректного исключения файлов и директорий из контроля версий.
- [x] **Форматирование `.svelte` файлов**: Применено автоматическое форматирование всех `.svelte` файлов с использованием Prettier. Исправлены отступы, выравнивание атрибутов и другие стилистические ошибки. Закоммичен файл `src/lib/components/admin/Functions.svelte`.
- [x] **Исправлено переключение разделов в студии**: Меню навигации в студии теперь корректно реагирует на клики и переключает вкладки через URL-параметр (`/studio?tab=chat`).
- [x] **Глобальная тема применяется по всему приложению**: Изменения темы теперь отражаются на всех страницах через CSS-классы `dark`/`light` на `document.documentElement`.
- [x] **Аутентификация сохраняется при обновлении страницы**: Токен не удаляется при временных ошибках сети или бэкенда; перенаправление на страницу логина происходит только при невалидном токене (401).

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

## Новые улучшения (2026-11-08)

- [x] **XLSX — все листы**: при загрузке `.xlsx` загружаются все листы (через `ExcelLoader`)
- [x] **Поддержка `.doc`**: обработка старых форматов Word через `Unstructured` или `Tika`
- [x] **Контекстное переупорядочивание**: гибкое ранжирование с учётом истории диалога
- [x] **Мульти-стратегия поиск**: векторный + BM25 + графовый поиск (через `orchestrate_retrieval`)
- [x] **Интерактивная оценка качества RAG**: UI для thumbs up/down и сбора обратной связи
- [x] **Аудит с настраиваемым сроком хранения**: `CODER_AUDIT_RETENTION_DAYS` + `POST /audit/cleanup`
- [x] **Оптимизация размеров чанков ≤500KB**: ленивая загрузка тяжелых зависимостей (pyodide, xterm, three) и настройка Vite для уменьшения размеров начального бандла.

### Оптимизация чанков — детали (~2026-11-08)
**Проблема:** Из-за тяжёлых библиотек (`pyodide` ~3.5MB, `three`, `@xterm/xterm`) чанки превышают 500KB (макс. 1.93MB).

**Решения:**
1. `src/lib/workers/pyodide.worker.ts` — обернуть `loadPyodide` в динамический `import()`.
2. `src/lib/components/chat/XTerminal.svelte` — ленивая загрузка `@xterm/xterm`.
3. `src/lib/components/chat/Model3DViewer.svelte` — ленивая загрузка `three`.
4. `vite.config.ts`:
   - Снизить `chunkSizeWarningLimit` до 500
   - Добавить `manualChunks` для разделения vendor-блоков (`pyodide`, `three`, `xterm`, `jszip`, `jspdf`, `mermaid` и др.)
5. Рассмотреть загрузку `pyodide`, `transformers`, `three` через CDN (отдельные `<script>` теги).

**Критерии успеха:** Все чанки ≤ 500KB (`npm run build` → `.svelte-kit/output/client/_app/immutable/chunks/*.js`).
**Верификация:** Запуск `npm run build` → проверка размеров чанков + тестирование функционала (код-блоки, терминал, 3D-модели).

## Задачи на будущее

- [ ] Реализация новых функций и улучшений интерфейса.
- [ ] Оптимизация производительности (тренд-анализ, оптимизация тяжелых загрузок).
- [ ] Документация новых функций (руководства для администраторов и пользователей).

## Документация

Для получения дополнительной информации о настройке и использовании Open WebUI, пожалуйста, ознакомьтесь с [документацией](https://docs.openwebui.com/).