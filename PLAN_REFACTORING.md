# Детальный план рефакторинга и оптимизации Open WebUI

**Цель:** уменьшить количество ошибок при программировании, убрать конфликты стека, разбить большие файлы, стабилизировать сборку и запуск.

**Статус:** черновик (требует согласования перед внесением изменений)

---

## 0. Текущие критические проблемы (must fix first)

| № | Проблема | Файл | Симптом | Приоритет |
|---|----------|------|---------|-----------|
| 0.1 | Конфликт SvelteKit v3: `app/stores` удалены | `src/lib/components/` | `Uncaught Error: svelte.dev/e/kit/app_stores_removed`, белый экран | **Критично** |
| 0.2 | Пустой `loader.js` (0 байт) | `build/static/loader.js` | Приложение не инициализируется при чистой сборке | **Критично** |
| 0.3 | `eslint: ^4.0.0` + `@eslint/js: ^10.0.0` + `eslint-config-prettier: ^10.1.8` | `package.json` | Конфликты правил линтера, нестабильный lint | Высокий |

---

## Этап 1. Исправление критичных ошибок (блокер запуска)

### 1.1. Исправить импорты SvelteKit stores
- **Проблема:** `@sveltejs/kit@^3` удалил `app/stores`. Код импортирует старые сторы → рантайм-ошибка.
- **Действие:** найти все импорты `from '$app/stores'` в `src/` и заменить на актуальный API SvelteKit v3 (`$app/navigation`, `$app/stores` — только `page`, `navigating`; остальное — собственные сторы в `src/lib/stores`).
- **Файлы:** `src/lib/components/+layout.svelte` (строка ~1176), `src/lib/apis/`, `src/lib/stores/`.
- **Альтернатива:** откатить `@sveltejs/kit` до v2 (größere изменения в роутинге).

### 1.2. Исправить пустой `loader.js`
- **Проблема:** `build/static/loader.js` = 0 байт, vite не генерирует его, HTML ссылается на него.
- **Действие:** либо убрать ссылку на `loader.js` из `src/app.html` (инициализация уже через inline-скрипт), либо заполнить актуальным кодом загрузчика.
- **Файлы:** `src/app.html`, `vite.config.ts` (проверить, почему не копируется).

### 1.3. Унифицировать версии ESLint
- **Действие:** привести `eslint`, `@eslint/js`, `eslint-config-prettier`, `eslint-plugin-svelte` к совместимым major-версиям (рекомендуется ESLint v9 + flat config `eslint.config.js`, который уже есть).
- **Файл:** `package.json`.

---

## Этап 2. Разбиение больших файлов

### 2.1. Бэкенд (Python)

**`backend/open_webui/main.py` (~2975 строк)** — разделить на:
- `main.py` — только создание FastAPI приложения и подключение роутеров
- `lifespan.py` — события запуска/остановки (загрузка моделей, БД, планировщик)
- `seed.py` — seed_defaults, инициализация данных
- `middleware_registry.py` — регистрация middleware

**`backend/open_webui/config.py` (~3399 строк)** — разделить на:
- `config/__init__.py` — точка входа
- `config/rag.py` — настройки RAG, эмбеддинги, чанки
- `config/auth.py` — аутентификация, OAuth, секреты
- `config/ui.py` — темы, каналы, пользовательский интерфейс
- `config/feature_flags.py` — флаги возможностей (ENABLE_*)

**`backend/open_webui/utils/middleware.py` (~5395 строк)** — разделить на:
- `middleware/auth.py`
- `middleware/cors.py`
- `middleware/logging.py`
- `middleware/rate_limit.py`

### 2.2. Фронтенд (Svelte)

**`src/lib/components/+layout.svelte`** — разделить на компоненты:
- `Header.svelte` — верхняя панель
- `Sidebar.svelte` — левое меню
- `ThemeToggle.svelte` — переключатель темы
- `AuthGuard.svelte` — защита роутов
- `SplashScreen.svelte` — экран загрузки

**`src/lib/apis/`** — крупные файлы разделить по сущностям:
- `chats.api.ts`, `models.api.ts`, `knowledge.api.ts`, `coder.api.ts`, `auth.api.ts`

**`src/lib/stores/`** — вынести общие сторы из компонентов в отдельные файлы.

---

## Этап 3. Стабилизация стека (без конфликтов)

### 3.1. Node / npm
- Закрепить `node: 22.23.3` и `npm: 12.2.1` в `.nvmrc` и CI.
- Добавить проверку версий в `Dockerfile` (уже частично сделано).

### 3.2. Vite / Rolldown / Tailwind
- Текущий стек: `vite: ^8.0.12` + `rolldown` + `@tailwindcss/oxide`. Нативные биндинги уже ломались на Alpine.
- **Решение:** оставить только Debian/glibc образы (уже в Dockerfile), добавить проверку в CI на целевую платформу.
- Рассмотреть фиксацию версий нативных зависимостей в `package-lock.json`.

### 3.3. Pyodide
- `pyodide: ^314.0.7` — тяжёлая зависимость, увеличивает бандл.
- **Решение:** вынести в опциональный флаг сборки `VITE_PYODIDE=true/false`, по умолчанию отключён для production.

### 3.4. Python зависимости
- `requirements.txt` — проверить на конфликты версий, добавить pin-версии для критичных пакетов (fastapi, sqlalchemy, sentence-transformers).
- Добавить `pip-compile` или `uv pip compile` для детерминированных блокировок.

---

## Этап 4. Уменьшение ошибок при программировании

### 4.1. TypeScript strict
- **Действие:** в `tsconfig.json` включить `strict: true`, `noImplicitAny: true`, `strictNullChecks: true`.
- Постепенно исправить ошибки типизации (не все сразу, а по модулям).

### 4.2. Python типизация
- Добавить `mypy` или `pyright` в CI.
- Добавить аннотации типов для новых функций в `backend/open_webui/`.

### 4.3. Pre-commit hooks
Усилить `.pre-commit-config.yaml`:
- `ruff format` для Python
- `svelte-check` для Svelte
- `mypy` / `pyright` для Python
- Проверка на пустые статические файлы (`loader.js`, `custom.css` = 0 байт)

### 4.4. Единый источник конфигурации
- `.env` читается bash (`start.sh`), Python (`env.py`), и напрямую. Риск рассинхрона.
- **Решение:** вынести парсинг `.env` в один общий модуль, использовать его везде.

### 4.5. CI / GitHub Actions
Добавить этапы:
1. `lint` (eslint + ruff)
2. `typecheck` (tsc + mypy)
3. `build-frontend` (npm run build, проверка на пустые файлы в `build/static/`)
4. `build-docker` (docker build, проверка что образ запускается)
5. `test` (vitest + pytest)

---

## Этап 5. Docker / деплой

### 5.1. Исправить сборку образа
- Текущий образ собран без рабочего фронтенда (пустые `loader.js`, `custom.css`).
- **Решение:** добавить в CI шаг проверки что `build/static/loader.js` и `build/static/custom.css` не пустые после `npm run build`.
- Добавить healthcheck для фронтенда (проверка `/health`).

### 5.2. Разделение образов
- Рассмотреть разделение на `open-webui-backend` (только Python) и `open-webui-frontend` (только статика), чтобы ускорять пересборку при изменении только одной части.

---

## Приоритизация и примерные сроки

| Этап | Задачи | Срок | Зависимости |
|------|--------|------|-------------|
| 1 | Исправить SvelteKit импорты, loader.js, ESLint версии | 1-2 дня | — |
| 2 | Разбить main.py, config.py, layout.svelte | 3-5 дня | Этап 1 |
| 3 | Унифицировать стек (Node, Vite, Pyodide, Python deps) | 2-3 дня | Этап 1 |
| 4 | TypeScript strict, mypy, pre-commit, CI | 3-5 дня | Этап 2, 3 |
| 5 | Docker стабильность, разделение образов | 2-3 дня | Этап 1, 4 |

**Общая оценка:** 2-3 недели при последовательной работе.

---

## Следующие действия (после согласования)

1. Согласовать подход к SvelteKit (откат до v2 или миграция на v3 API).
2. Согласовать список файлов для первого сплита (main.py / config.py / layout.svelte).
3. Я вношу изменения только после вашего одобрения каждого этапа.

Готовы начать с Этапа 1?