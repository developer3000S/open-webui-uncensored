#!/usr/bin/env bash
set -euo pipefail

# ---------------------------------------------------------------------------
# Build and run the Open WebUI Docker container locally.
# The image is ALWAYS built from the local sources — never pulled from Docker Hub.
# ---------------------------------------------------------------------------

readonly IMAGE="openwebui/open-webui"
readonly CONTAINER="open-webui"
readonly VOLUME="open-webui-rus_open-webui"
readonly HOST_PORT="${OPEN_WEBUI_PORT:-8083}"
readonly CONTAINER_PORT=8080

# Sidecar для слоя GraphRAG (open_webui/retrieval/graphrag). Поднимается всегда
# — без NEO4J_URI приложение работает как раньше, но держать сервер дешевле,
# чем терять граф при первом включении. Память ограничена: хост живёт с 16 GB
# и CPU-Ollama, который важнее по приоритету.
readonly NEO4J_IMAGE="neo4j:5.26"
readonly NEO4J_CONTAINER="open-webui-neo4j"
readonly NEO4J_VOLUME="open-webui-rus_neo4j-data"
readonly NEO4J_BOLT_PORT="${NEO4J_BOLT_PORT:-7687}"
# Общая сеть для обоих контейнеров: приложение ходит к Neo4j по имени сервиса
# (bolt://open-webui-neo4j:7687), наружу граф не публикуется. Публикация на
# 127.0.0.1 ниже — только для отладки с хоста; host.docker.internal для bolt
# не подходит: он ведёт на шлюз bridge, а не на loopback хоста.
readonly DOCKER_NETWORK="open-webui-rus_net"

REPO_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &>/dev/null && pwd)
readonly REPO_DIR
readonly ENV_FILE="${REPO_DIR}/.env"
# /app/backend is the image WORKDIR, so BASE_DIR in env.py resolves to /app.
readonly CONTAINER_ENV_FILE="/app/.env"

# Пароль Neo4j берётся из .env (единственный источник настроек деплоя), не из
# окружения shell: тот же файл монтируется в контейнер и читает его backend.
# Служебный доступ к локальному графу, не секрет продакшена.
NEO4J_PASSWORD=""
if [[ -f "$ENV_FILE" ]]; then
  NEO4J_PASSWORD=$(grep -E '^[[:space:]]*NEO4J_PASSWORD=' "$ENV_FILE" | tail -1 | cut -d= -f2- | tr -d "\"'" || true)
fi
readonly NEO4J_PASSWORD="${NEO4J_PASSWORD:-MyPasword12345}"

# ---------------------------------------------------------------------------
# .env — единственный источник настроек деплоя.
# ---------------------------------------------------------------------------
# Файл монтируется в контейнер, а не только передаётся через --env-file:
# приоритет над таблицей config в SQLite даётся именно именам, объявленным
# в файле (backend/open_webui/env.py перечитывает его с override=True), и только
# чтение файла снимает кавычки, которые docker run --env-file оставляет в значении.
if [[ ! -f "$ENV_FILE" ]]; then
  echo "❌ Не найден ${ENV_FILE}"
  echo "   Скопируйте шаблон и заполните: cp ${REPO_DIR}/.env.example ${ENV_FILE}"
  exit 1
fi

if ! grep -Eq "^[[:space:]]*(export[[:space:]]+)?OLLAMA_BASE_URL[[:space:]]*=[[:space:]]*['\"]?https?://" "$ENV_FILE"; then
  echo "⚠️  В ${ENV_FILE} нет явного OLLAMA_BASE_URL."
  echo "   Изнутри контейнера localhost — это сам контейнер; Ollama на хосте:"
  echo "   OLLAMA_BASE_URL='http://host.docker.internal:11434'"
fi

# Очистка используемых портов (освобождаем только процессы, слушающие порт)
clear_port() {
  local port=$1
  if command -v fuser &>/dev/null; then
    if fuser "$port/tcp" &>/dev/null 2>&1; then
      echo "⚠️  Порт $port уже используется. Освобождаем..."
      fuser -k "$port/tcp" 2>/dev/null || true
    fi
  elif command -v lsof &>/dev/null; then
    if lsof -i :"$port" &>/dev/null 2>&1; then
      echo "⚠️  Порт $port уже используется. Освобождаем..."
      local pids
      pids=$(lsof -t -i :"$port" 2>/dev/null || true)
      if [[ -n "$pids" ]]; then
        kill $pids 2>/dev/null || true
      fi
    fi
  fi
}

# Освобождение имени контейнера (docker run не перезаписывает существующее имя)
stop_container() {
  if docker inspect "$CONTAINER" &>/dev/null; then
    echo "⚠️  Контейнер ${CONTAINER} уже существует. Удаляем..."
    docker rm -f "$CONTAINER" 2>/dev/null || true
  fi
}

# Neo4j для слоя GraphRAG. В отличие от контейнера приложения, НЕ пересоздаётся
# при каждом запуске: граф переживает пересборку образа, а данные в томе.
# Пересоздание — только если контейнер пропал или изменился проброшенный порт.
start_neo4j() {
  if docker inspect "$NEO4J_CONTAINER" &>/dev/null; then
    if [ "$(docker inspect -f '{{.State.Running}}' "$NEO4J_CONTAINER")" = "true" ]; then
      echo "♻️  Neo4j уже запущен (${NEO4J_CONTAINER}, bolt ${NEO4J_BOLT_PORT})"
      return 0
    fi
    echo "▶️  Запуск существующего Neo4j (${NEO4J_CONTAINER})..."
    docker start "$NEO4J_CONTAINER" >/dev/null
    return 0
  fi

  if ! docker image inspect "$NEO4J_IMAGE" &>/dev/null; then
    echo "📥 Загрузка образа ${NEO4J_IMAGE}..."
    if ! docker pull "$NEO4J_IMAGE"; then
      echo "⚠️  Образ не скачан — GraphRAG будет недоступен (приложение работает без него)."
      return 0
    fi
  fi

  docker volume create "$NEO4J_VOLUME" >/dev/null 2>&1 || true
  echo "🗄️  Поднимаю Neo4j (${NEO4J_CONTAINER}, bolt ${NEO4J_BOLT_PORT})..."
  # Лимиты памяти обязательны: хост 16 GB, и на нём ещё Ollama на CPU.
  # 7474 (HTTP/Browser) не публикуется; bolt — только на loopback, для отладки
  # с хоста. Приложение ходит по имени сервиса через DOCKER_NETWORK.
  docker run -d \
    -p "127.0.0.1:${NEO4J_BOLT_PORT}:7687" \
    -v "${NEO4J_VOLUME}:/data" \
    -e "NEO4J_AUTH=neo4j/${NEO4J_PASSWORD}" \
    -e "NEO4J_server_memory_heap_max__size=1G" \
    -e "NEO4J_server_memory_pagecache_size=512M" \
    --memory 2g --memory-swap 3g \
    --network "$DOCKER_NETWORK" \
    --name "$NEO4J_CONTAINER" \
    --restart always \
    "$NEO4J_IMAGE" >/dev/null
}

clear_port "$HOST_PORT"
stop_container
# Сеть должна существовать до обоих контейнеров: приложение резолвит Neo4j по
# имени сервиса open-webui-neo4j.
docker network create "$DOCKER_NETWORK" >/dev/null 2>&1 || true
start_neo4j

echo "========================================="
echo "Open WebUI Docker Runner (только локальная сборка)"
echo "========================================="

echo "🔨 Локальная сборка образа ${IMAGE} — загрузка из хаба запрещена..."
docker build -t "$IMAGE" .

echo "💾 Проверка тома данных ${VOLUME}..."
docker volume create "$VOLUME" >/dev/null 2>&1 || true

echo "🚀 Запуск контейнера ${CONTAINER}..."
# Файл монтируется, а не передаётся через --env-file. Причин две:
#   1. env.py читает именно файл, чтобы знать, каким именам разрешено перекрывать
#      таблицу config в SQLite (--env-file таких имён не даёт);
#   2. docker run --env-file не снимает кавычки, так что FORWARDED_ALLOW_IPS='*'
#      дошёл бы до uvicorn литералом с апострофами. start.sh разбирает
#      смонтированный файл тем же парсером, что и env.py, — кавычки снимаются.
docker run -d \
  -p "${HOST_PORT}:${CONTAINER_PORT}" \
  --add-host=host.docker.internal:host-gateway \
  --network "$DOCKER_NETWORK" \
  -v "${VOLUME}:/app/backend/data" \
  -v "${ENV_FILE}:${CONTAINER_ENV_FILE}:ro" \
  --ulimit nofile=65536:524288 \
  --name "$CONTAINER" \
  --restart always \
  "$IMAGE"

echo "⏳ Ожидание готовности сервиса..."
for i in $(seq 1 60); do
  if curl -s --head --fail "http://localhost:${HOST_PORT}" >/dev/null 2>&1; then
    echo "✅ Open WebUI запущен!"
    echo ""
    echo "🌐 Доступен по адресу: http://localhost:${HOST_PORT}"
    echo "📁 Данные сохраняются в томе: ${VOLUME}"
    echo ""
    echo "📋 Полезные команды:"
    echo "   docker logs ${CONTAINER}        - просмотр логов"
    echo "   docker exec -it ${CONTAINER} bash - войти в контейнер"
    echo "   docker stop ${CONTAINER}        - остановить контейнер"
    echo "   docker start ${CONTAINER}       - запустить контейнер"
    echo "========================================="
    exit 0
  fi
  sleep 5
done

echo "❌ Ошибка: сервис не доступен по адресу http://localhost:${HOST_PORT}"
docker logs "$CONTAINER" --tail 50 2>/dev/null || true
exit 1