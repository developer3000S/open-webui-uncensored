#!/usr/bin/env bash
set -euo pipefail

# ---------------------------------------------------------------------------
# Поднимает стек целиком: open-webui, Neo4j и Uncensored AI Studio.
#
# Конфигурация контейнеров живёт в docker-compose.yaml — тома, общая сеть,
# порты и healthcheck описаны в одном месте, а не дублируются здесь.
# Параметры сборки/запуска (порты, пароль Neo4j, upstream студии) берутся
# из .env; compose читает его сам.
# ---------------------------------------------------------------------------

REPO_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &>/dev/null && pwd)
readonly REPO_DIR
readonly COMPOSE_FILE="${REPO_DIR}/docker-compose.yaml"
readonly ENV_FILE="${REPO_DIR}/.env"

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

if ! docker compose version &>/dev/null; then
  echo "❌ Нет плагина docker compose (Compose V2)."
  echo "   Установите его: https://docs.docker.com/compose/install/"
  exit 1
fi

echo "========================================="
echo "Open WebUI + Neo4j + Uncensored AI Studio"
echo "========================================="
echo "🔨 Сборка образов из локальных исходников..."
# --build всегда пересобирает образы из локальных исходников: pull из реестра
# не используется, а изменения в backend/ и studio/ должны попадать в образ.
# --pull подтягивает только базовые образы (node, neo4j) ради свежих пакетов.
docker compose -f "$COMPOSE_FILE" --env-file "$ENV_FILE" up -d --build --pull always

OPEN_WEBUI_PORT="$(grep -E '^[[:space:]]*OPEN_WEBUI_PORT=' "$ENV_FILE" | tail -1 | cut -d= -f2- | tr -d "\"' " || true)"
OPEN_WEBUI_PORT="${OPEN_WEBUI_PORT:-8083}"
readonly OPEN_WEBUI_PORT

echo "⏳ Ожидание готовности сервисов..."
# open-webui зависит от healthy-Neo4j (depends_on в compose), поэтому ждать
# достаточно его одного: swagger на /health означает, что приложение запустилось.
for _ in $(seq 1 90); do
  if curl -s --head --fail "http://localhost:${OPEN_WEBUI_PORT}" >/dev/null 2>&1; then
    echo "✅ Стек запущен!"
    echo ""
    echo "🌐 Open WebUI:        http://localhost:${OPEN_WEBUI_PORT}"
    echo "🌐 AI Студия:         http://localhost:${OPEN_WEBUI_PORT}/studio/"
    echo "🗄️  Neo4j bolt:        127.0.0.1:7687 (только для отладки)"
    echo ""
    echo "📋 Полезные команды:"
    echo "   docker compose logs -f                 - логи всех сервисов"
    echo "   docker compose logs -f open-webui       - логи Open WebUI"
    echo "   docker compose logs -f studio           - логи студии"
    echo "   docker compose down                     - остановить стек (данные остаются)"
    echo "   docker compose up -d                    - поднять снова, без пересборки"
    echo "   docker exec -it open-webui bash         - войти в контейнер"
    echo "========================================="
    exit 0
  fi
  sleep 5
done

echo "❌ Open WebUI не доступен по адресу http://localhost:${OPEN_WEBUI_PORT}"
docker compose -f "$COMPOSE_FILE" logs --tail 60 open-webui studio 2>/dev/null || true
exit 1
