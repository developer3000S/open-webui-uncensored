# Отличия от оригинального Open WebUI

Этот репозиторий — форк [open-webui-uncensored](https://github.com/developer3000s/open-webui-uncensored) с собственной разработкой поверх. Файл описывает, чем проект отличается от апстрима и что из этого следует при обновлении.

> Данные сверки: **2026-10-15**, база — релиз `v0.10.2`.

---

## Содержание

- [База: снапшот, а не живой форк](#база-снапшот-а-не-живой-форк)
- [Отличия в зависимостях](#отличия-зависимостей)
- [Отличия кода и инфраструктуры](#отличия-кода-и-инфраструктуры)
- [Что это значит при обновлении](#что-это-значит-при-обновлении)

---

## База: снапшот, а не живой форк

- Версия ядра — **Open WebUI 0.10.2**: `package.json` форка (`"open-webui@0.10.2"`) идентичен тегу `v0.10.2` в апстриме.
- Общей git-истории с апстримом **нет**: история начинается с чистого `Initial commit`, ремоут один (`developer3000S/open-webui-uncensored`), upstream-remote не подключён.
- Следствие: релизы и security-фиксы апстрима **не подтекают сами**. Обновление = перенос нового снапшота и повторное наложение правок (см. последний раздел).
- Ядро Open WebUI не переписано: стек тот же — SvelteKit 2 / Svelte 5 + TS + Vite + Tailwind 4 на фронте, FastAPI + SQLAlchemy + Alembic на бэке.

---

## Отличия зависимостей

Diff `backend/requirements.txt` против апстрима `v0.10.2`:

| Пакет | Апстрим 0.10.2 | Этот форк | Зачем |
|---|---|---|---|
| `neo4j` | — | **+ 5.26.0** | Драйвер слоя GraphRAG (`open_webui/retrieval/graphrag`). Без APOC/GDS — векторный поиск через нативный индекс Neo4j |
| `google-genai` | 1.66.0 | **2.10.0** | Обновлён до мажора 2 |
| остальное ядро | fastapi 0.136.3, sqlalchemy 2.0.50, langchain 1.2.10, chromadb 1.5.9, transformers 5.5.4, sentence-transformers 5.5.1, openai 2.29.0, anthropic 0.86.0, mcp 1.27.2, python-socketio 5.16.2 | пин-в-пин | — |

---

## Отличия кода и инфраструктуры

| Область | Форк | Оригинал 0.10.2 |
|---|---|---|
| **RAG** | Adaptive RAG-оркестратор: `backend/open_webui/retrieval/graphrag/` — 24 модуля (orchestrator, policy, circuit_breaker, query_rewrite, query_understanding, reranker, LLM-judge groundedness, shadow mode). Trace-store в SQLite `orchestrator.db`, admin observability API, explain-trace API | Обычный retrieval-пайплайн |
| **Граф знаний** | GraphRAG на Neo4j 5.26 (extractor, planner, response_synthesizer, evaluation) | Нет |
| **Compose-стек** | Единый стек: `open-webui + neo4j + uncensored-studio`. `.env` смонтирован в контейнер и разбирается `backend/start.sh` + `env.py`; имена из `.env` приоритетнее хранимой `config`-таблицы | Обычный контейнер open-webui, `.env` декоративный |
| **Studio** | Интеграция Uncensored AI Studio (Stable Diffusion, llama-server на `:10086`, Whisper, Kokoro) через iframe-прокси `/studio`, сайдбар, фильтр источников моделей | Нет |
| **Контекст окна** | Авто-детект context window моделей, обрезка длинных запросов, admin override `context_length`, бейдж контекста в селекторе моделей | Нет |
| **Coder** | Собственный раздел `/coder`: GitHub OAuth (токены только на сервере, AES-256-GCM), обзор репозитория/веток/файлов, чат с кодовой моделью и системным промптом Coder, структурированный Change Set с серверной валидацией и unified diff, экспорт в новую ветку через Git Data API с обязательным Pull Request, идемпотентность экспорта, аудит в БД. Feature flag `CODER_ENABLED` (по умолчанию выключен). Бэк: `models/coder.py`, `routers/coder.py`, `utils/coder/*`; фронт: `routes/(app)/coder`, `apis/coder`, `components/coder`. ТЗ — `Coder.md` | Нет |
| **Эмбеддинги** | Прогрессивная индексация с таймаутом и возобновлением; отмена из UI; прогресс-бар (XHR-байты + SSE «Embedding N/M»); переиспользование векторов дубликатов (`RAG_DEDUP_DUPLICATE_FILES`); HTTP-таймауты вместо вечного зависания; движок **Mistral** | Нет |
| **Реранкер** | Локальный CrossEncoder (внутри оркестратора/GraphRAG) | Внешний Cohere-совместимый endpoint |
| **i18n** | Переводы Playwright Search Engine на 62 локали | — |
| **Прочие фиксы** | retry import, oauth, secret key в volume, `--proxy-headers` в start.sh, nofile ulimits в compose | — |

---

## Что это значит при обновлении

- Апстрим-фиксы после 0.10.2 **сами не приходят**: обновление = перенос свежего снапшота Open WebUI и повторное наложение форк-правок (конфликты почти гарантированы в `retrieval/`, `env.py`, compose-файлах).
- Перед обновлением стоит сверить этот файл с фактическим состоянием: состав graphrag-модулей, список кастомных движков эмбеддингов и compose-сервисы.
- Быстрая проверка базы: `package.json` форка vs `package.json` тега `v0.10.2` апстрима; diff `backend/requirements.txt` — там должны отличаться только `neo4j` и `google-genai`.
