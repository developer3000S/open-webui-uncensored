# Адаптивный RAG-оркестратор — руководство

Документ описывает **реализацию** системы динамической композиции RAG-стратегий,
построенную по техническому заданию [`RAG-ТЗ.md`](./RAG-ТЗ.md). ТЗ задаёт
архитектуру и контракты; эта страница — практическая справка: что где лежит,
как включается, чем настраивается и как диагностируется.

## 1. Что изменилось в системе RAG

Раньше путь поиска был статическим: векторный (при необходимости hybrid) поиск
по чанкам + опциональная графовая augmentation (`maybe_augment_with_graph`).
Теперь поверх него работает оркестратор, реализующий цикл из ТЗ §4–§10:

```
Preprocessing → Query Understanding → Policy / Confidence / Planner
        → Execution Layer (native | hybrid | graph | agentic | tool)
        → Response Evaluation → Synthesis → Trace + Feedback
```

Ключевые свойства реализации:

- **Fail-closed / graceful degradation.** Оркестратор никогда не может «сломать»
  чат: при любом внутреннем сбое или отказе от маршрутизации (`abstain`)
  запрос выполняется прежним базовым путём (вектор/hybrid). Точка входа —
  `get_sources_from_items` в `backend/open_webui/retrieval/utils.py`.
- **Zero-trust политика (§6).** Запросы с признаками prompt-injection, PII-риском
  или недоступными источникам получают deny-постуру; автономия агентов ограничена
  для критичных доменов.
- **Лестница эскалации (§10.2).** Native → Hybrid → Graph → Agentic по уверенности
  и качеству оценки; деэскалация к более дешёвому пайплайну при перерасходе
  бюджета (§10.3). Цикл ограничен одним рангом эскалации.
- **Объяснимость (§15.6).** Каждый план несёт `rationale`, каждый ответ — статус
  (`answered / uncertain / clarification / refused`), использованные пайплайны,
  цитаты и предупреждения; полная трасса пишется в хранилище трейсов.

## 2. Структура кода

Все модули — в `backend/open_webui/retrieval/graphrag/`:

| Модуль | Слой (ТЗ) | Назначение |
| --- | --- | --- |
| `models.py` | §9 | Pydantic-контракты: QueryContext, QueryAnalysis, PolicyDecision, ConfidenceEstimate, ExecutionPlan, CandidateResponse, EvaluationReport, FinalResponse, TraceRecord, FeedbackRecord |
| `settings.py` | §13.2–13.3 | Конфигурация: feature-флаги, пороги уверенности, бюджеты/таймауты. Env-дефолты + перезапись из Config (`rag.orchestrator.*`) |
| `preprocessing.py` | §4.1 | Нормализация, детект языка, анти-injection скрининг, разрешение анафоры по истории, cache_key с изоляцией по tenant/правам |
| `query_understanding.py` | §4.2.3 | Классификация интентов (16 типов), сложность, ambiguity, answerability, safety_risk — без LLM-вызовов |
| `policy.py` | §4.2.2 | Policy Engine: JSON-документ правил (default/role/tenant), deny по safety-флагам, фильтр доступных пайплайнов |
| `confidence.py` | §4.2.4 | Оценка уверенности по сигналам + историческая калибровка по обратной связи; recommended_mode: fast_path/standard/deep/ensemble/clarification/refusal |
| `planner.py` | §4.2.5, §10.1–10.3 | Матрица маршрутизации как данные; режим single/parallel/sequential; бюджеты, retry, rationale; лестница эскалации |
| `context_manager.py` | §4.4.2 | Сборка контекста в token-budget: приоритеты, резерв под graph-контекст, суммаризация переполнения |
| `pipeline_adapters.py` | §4.3 | Пять пайплайнов за единым контрактом: native (вектор), hybrid (BM25+вектор+rerank), graph (Neo4j, ACL по gid), agentic (ограниченный цикл, read-only инструменты), tool (внешний поиск, маркировка `external_unverified`) |
| `execution.py` | §4.3–4.4 | Диспетчер планов: параллельное/последовательное исполнение, per-task таймауты/retry, глобальный дедлайн, учёт бюджетов, дедуп кандидатов, предикат `insufficient()` |
| `evaluation.py` | §4.5 | Relevance, Groundedness (классификация claims), Contradiction Detection, Citation Verification, Safety Filter → EvaluationReport с recommended_action |
| `response_synthesizer.py` | §4.6 | Синтез FinalResponse: select/merge/clarify/uncertain/refuse, citations, warnings, request_id для аудита |
| `trace_store.py` | §9.8, §4.7, §10.5, §11.3 | SQLite-хранилище трасс и фидбека (WAL), retention-чистка, метрики качества; персистентный кэш ответов (переживает рестарт); запись best-effort |
| `orchestration.py` | §10.4 | Сквозной контроль-цикл и интеграция: `orchestrate_retrieval(...)` возвращает sources в legacy-формате либо `None` (abstain → базовый путь). Включает shadow-прогоны (§3) и follow-up подсказки |
| `orch_api.py` | рец. 1.1, §15.6 | Сервисный слой admin-API: снапшот статуса, фильтрованный список трасс, explain-проекция «почему такой ответ», приём фидбека с калибровкой, policy get/put с валидацией, горячая перезапись настроек, генератор follow-up вопросов |
| `query_rewrite.py` | рец. 2.2 | Дешёвый rewrite без LLM: декомпозиция составных вопросов («сравни X и Y» → подзапросы), причинные варианты, тематическая привязка по истории, HyDE-lite через лексикон сущностей |
| `reranker.py` | рец. 2.1 | Опциональный cross-encoder rerank (`sentence-transformers`, ленивая загрузка модели, graceful fallback при отсутствии) |
| `circuit_breaker.py` | рец. 3.2 | Circuit breaker для внешних зависимостей (Neo4j, embedding-провайдер): после N подряд отказов зависимость пропускается на время cool-off вместо оплаты таймаута каждым запросом |

Существующие модули `extractor.py`, `worker.py`, `neo4j_client.py`,
`retrieval.py`, `prompts.py`, `orchestrator.py` (legacy-шлюз `should_use_graph`)
остались на месте и продолжают обслуживать индексацию графа и fallback-путь.

## 3. Включение и выключение

Оркестратор включён по умолчанию, но полностью отключается одной переменной:

```env
RAG_ORCHESTRATOR_ENABLED=false   # мгновенный возврат к прежнему статическому пути
```

Feature-флаги отдельных слоёв (все — env-дефолты, все — перезаписываемы из
Admin → Settings, см. §5):

| Переменная | По умолчанию | Что включает |
| --- | --- | --- |
| `RAG_ORCHESTRATOR_ENABLED` | `true` | Весь оркестратор |
| `GRAPHRAG_ENABLED` | `false` | Пайплайн `graph_rag` (нужен Neo4j и проиндексированный граф) |
| `ORCH_HYBRID_ENABLED` | `true` | Пайплайн `hybrid_rag` |
| `ORCH_AGENTIC_ENABLED` | `false` | Пайплайн `agentic_rag` (LLM-цикл с инструментами) |
| `ORCH_WEB_TOOLS_ENABLED` | `false` | Пайплайн `tool_pipeline` (внешний веб-поиск) |
| `ORCH_ENSEMBLE_ENABLED` | `true` | Параллельные/ансамблевые планы |
| `ORCH_EVALUATION_ENABLED` | `true` | Слой оценки кандидатов (§4.5) |
| `ORCH_CITATION_VERIFICATION` | `true` | Проверка цитат (§4.5.6) |
| `ORCH_SAFETY_FILTER` | `true` | Safety-фильтр ответа (§4.5.7, §6.3) |
| `ORCH_CACHE_ENABLED` | `false` | Кэш результатов (персистентный SQLite + in-process LRU; ключ изолирован по tenant и правам, §6.2) |
| `ORCH_TRACE_STORE` | `true` | Запись трасс и приём фидбека |

Переменные новых слоёв (спринты 1–4):

| Переменная | По умолчанию | Что включает |
| --- | --- | --- |
| `ORCH_SHADOW_PERCENT` | `0` | Shadow-режим: N% трафика прогоняется через оркестратор вхолостую (ответ берётся из baseline), трассы пишутся с меткой `shadow` — безопасное раскатывание и A/B-статистика |
| `ORCH_EVAL_LLM` | `false` | LLM-judge для groundedness-проверки claims (§4.5.4) вместо чисто эвристической оценки |
| `ORCH_CROSS_ENCODER` | `false` | Cross-encoder rerank в hybrid-пайплайне |
| `ORCH_CE_MODEL` | `cross-encoder/ms-marco-MiniLM-L6-v2` | Модель cross-encoder (`sentence-transformers`) |
| `ORCH_CE_MAX_DOCS` | `30` | Кап документов, подаваемых в reranker (защита latency-бюджета) |
| `ORCH_HYDE` | `false` | HyDE-lite расширение запроса через лексикон графовых сущностей |
| `ORCH_CB_THRESHOLD` | `3` | Подряд отказов зависимости до размыкания цепи (circuit breaker) |
| `ORCH_CB_RESET_S` | `60` | Cool-off окно перед half-open probe |
| `ORCH_CACHE_TTL_S` | `300` | TTL записей кэша ответов |
| `ORCH_TRACE_RETENTION_DAYS` | `90` | Retention трасс/фидбека/кэша (§10.5) |
| `ORCH_CONTEXT_TOKENS` | `8000` | Token-budget сборки контекста (§4.4.2) |

Query rewrite (рец. 2.2) включён всегда — он не требует LLM-вызовов:
декомпозиция составных вопросов, причинные варианты и тематическая привязка
по истории применяются автоматически в native/hybrid пайплайнах.

Режим маршрутизации: `GRAPHRAG_MODE=auto|off|force` (для графовой ветки,
наследуется из legacy-настройки).

## 4. Маршрутизация (сокращённо из §10.1)

Выбор пайплайна — данные, а не код (матрица в `planner.py`):

| Intent запроса | Основной пайплайн | Эскалация |
| --- | --- | --- |
| factual_lookup, definitional | native_rag | hybrid |
| comparison, summarization | hybrid_rag | graph |
| multi_hop, relational, temporal, causal | graph_rag | agentic |
| exploratory, unknown_entity | hybrid + graph (parallel) | agentic |
| procedural, configuration | native/hybrid | tool |
| external/current-events | tool_pipeline | — |
| unsafe / low answerability | clarification / refusal | — |

Пороги режима исполнения (`ConfidenceEstimate` → план):

- `≥ ORCH_CONF_SINGLE` (0.85) — один пайплайн (fast path);
- `≥ ORCH_CONF_PARALLEL` (0.65) — параллельно несколько пайплайнов;
- `< ORCH_CONF_ESCALATE` (0.45) — глубокий/ансамблевый путь либо clarification.

Бюджеты и таймауты (ms / units): `ORCH_MAX_LATENCY_MS=30000`,
`ORCH_MAX_COST_UNITS=1.0`, `ORCH_MAX_AGENT_STEPS=6`, `ORCH_MAX_TOOL_CALLS=8`,
`ORCH_MAX_CANDIDATES=4`, плюс per-pipeline `ORCH_NATIVE_TIMEOUT_MS`,
`ORCH_HYBRID_TIMEOUT_MS`, `ORCH_AGENTIC_TIMEOUT_MS`, `ORCH_TOOL_TIMEOUT_MS`,
`GRAPHRAG_QUERY_TIMEOUT` (сек, graph). Граф: `GRAPHRAG_TOP_ENTITIES=6`,
`GRAPHRAG_TRAVERSAL_DEPTH=2`, `GRAPHRAG_NEIGHBOR_LIMIT=12`.

Пороги приёмки оценки (§4.5.8): `ORCH_MIN_OVERALL_SCORE=0.45`,
`ORCH_MIN_GROUNDEDNESS=0.5`, `ORCH_MAX_UNSUPPORTED_RATIO=0.2`.

## 5. Управление из Admin → Settings

Каждый ключ таблицы настроек оркестратора доступен в персистентном Config под
префиксом `rag.orchestrator.<имя_поля>` — например
`rag.orchestrator.agentic_enabled`, `rag.orchestrator.conf_single`,
`rag.orchestrator.max_latency_ms`. Значения из Config имеют приоритет над env,
применяются на горячую (без рестарта). Если имя дополнительно закреплено в
`.env`, действует общий для проекта порядок приоритетов (см. README, раздел
«Конфигурация развёртывания»).

## 6. Наблюдаемость и обратная связь

- **Трассы (§9.8).** Каждый обработанный запрос пишет `TraceRecord` (query,
  intent, confidence, план, пайплайны, баллы оценки, статус ответа, latency/cost)
  в отдельную SQLite-базу `DATA_DIR/orchestrator.db` (WAL). Запись best-effort:
  сбой хранилища не влияет на ответ пользователю. Хранение регулируется
  retention-чисткой (§10.5).
- **Обратная связь (§4.7).** Рейтинги, привязанные к trace_id, накапливаются в
  той же базе и используются калибровкой уверенности (`record_outcome`):
  историческая точность по классам интентов напрямую влияет на будущую
  маршрутизацию (§11.3 — метрики дрейфа: `recent_feedback_quality`).
- **Админ-API** (`/api/v1/graphrag/orchestrator/*`, требуется admin — рец. 1.1):
  - `GET /status` — сводка оркестратора: флаги, состояние circuit breaker'ов, hit-rate кэша;
  - `GET /traces?intent=&pipeline=&status=&from=&to=&limit=` — фильтрованный список трасс; `GET /traces/{id}` — полная трасса с кандидатами и отчётом оценки;
  - `GET /explain/{trace_id}` — компактная проекция «почему такой ответ» для UI-панели объяснимости (§15.6);
  - `POST /feedback` — приём рейтингов (−1/+1 или 1..5), привязанных к trace_id, с немедленной калибровкой уверенности;
  - `GET /metrics?hours=24` — метрики дрейфа (§11.3): latency p50/p95, доли refusals/clarifications, средний groundedness по пайплайнам, качество фидбека;
  - `GET /policy` / `PUT /policy` — чтение и валидированная запись policy-as-code документа (§4.2.2);
  - `PATCH /settings` — горячая перезапись feature-флагов и порогов без рестарта.
- **Follow-up подсказки (рец. §4).** `orch_api.followup_suggestions()` строит до
  3 детерминированных уточняющих вопроса из извлечённых сущностей (дедуп по
  регистронезависимому ключу, исключение уже упомянутых в запросе).
- **Legacy-API графа** (`/api/v1/graphrag`): `POST /knowledge/{kb_id}/index`,
  `GET /knowledge/{kb_id}/status`, `DELETE /knowledge/{kb_id}`,
  `GET /knowledge/{kb_id}/graph` — управление графом знаний.

## 7. Безопасность (кратко, детали в ТЗ §6)

- Анти-injection скрининг на входе (§6.3): подозрительные запросы получают
  deny-постуру и safety-фильтр вывода.
- Zero-trust по умолчанию: источники ограничены правами пользователя
  (ACL-обход графа только по gid доступных файлов; кэш-ключ изолирован по
  tenant + правам, §6.2).
- Внешние результаты (`tool_pipeline`) маркируются `external_unverified` и не
  смешиваются с подтверждёнными утверждениями без явного статуса.
- Safety-фильтр синтеза маскирует секреты/PII и блокирует prompt-leakage.

## 8. Быстрый старт

```bash
# Минимальная конфигурация (в .env): оркестратор уже включён по умолчанию
VECTOR_DB=valkey
VALKEY_URL='valkey://localhost:6379'

# Опционально — графовый пайплайн:
GRAPHRAG_ENABLED=true
NEO4J_URI=bolt://neo4j:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=...
# затем индексация: POST /api/v1/graphrag/knowledge/{kb_id}/index

# Опционально — агентный слой (дороже по latency/cost):
ORCH_AGENTIC_ENABLED=true
```

Проверка деградации: `RAG_ORCHESTRATOR_ENABLED=false` + рестарт — система
ведёт себя ровно как до перестройки.

## 9. Тесты

Юнит-тесты существующего графового слоя запускаются как раньше:

```bash
python3 backend/tests/test_graphrag_extractor.py
python3 backend/tests/test_graphrag_neo4j.py
```

Тесты оркестратора (спринты 1–4) — pytest из каталога `backend/`
(`open_webui` должен быть в `PYTHONPATH`, плагин libtmux в CI отключают
`PYTEST_DISABLE_PLUGIN_AUTOLOAD=1` при необходимости):

```bash
cd backend
python3 -m pytest tests/test_orch_policy.py \
                  tests/test_orch_escalation.py \
                  tests/test_orch_sprint2.py \
                  tests/test_orch_sprint34.py -q
# 50 passed
```

Покрытие: матрица deny Policy Engine (§4.2.2), лестница эскалации §10.2 с
mock-таймаутами, query rewrite и cross-encoder фолбэк, shadow-режим,
персистентный кэш (переживание «рестарта»), жизненный цикл circuit breaker
(closed→open→half_open→closed и повторное opening по failed probe),
дедуп follow-up подсказок. Модули оркестрации импортируются без БД и внешних
сервисов (ленивые импорты Config/Neo4j), поэтому тестируются изолированно.
