#!/usr/bin/env bash
set -euo pipefail

# ---------------------------------------------------------------------------
# Поднимает стек целиком: open-webui, Neo4j и Uncensored AI Studio.
# Онлайн-режим: использует стандартные зависимости и доступ в интернет.
#
# Конфигурация контейнеров живёт в docker-compose.yaml — тома, общая сеть,
# порты и healthcheck описаны в одном месте, а не дублируются здесь.
# Параметры сборки/запуска (порты, пароль Neo4j, upstream студии) берутся
# из .env; compose читает его сам.
# ---------------------------------------------------------------------------

REPO_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &>/dev/null && pwd)"
readonly REPO_DIR
ENV_FILE="${REPO_DIR}/.env"
readonly ENV_FILE

# Проверка наличия файла .env
if [[ ! -f "$ENV_FILE" ]]; then
  echo "❌ Не найден ${ENV_FILE}"
  echo "   Скопируйте шаблон и заполните: cp ${REPO_DIR}/.env.example ${ENV_FILE}"
  exit 1
fi

# Проверка наличия OLLAMA_BASE_URL
if ! grep -qE "OLLAMA_BASE_URL.*=.*https?://" "$ENV_FILE"; then
  echo "⚠️  В ${ENV_FILE} нет явного OLLAMA_BASE_URL."
  echo "   Изнутри контейнера localhost — это сам контейнер; Ollama на хосте:"
  echo "   OLLAMA_BASE_URL='http://host.docker.internal:11434'"
fi

# Проверка наличия docker compose
if ! docker compose version &>/dev/null; then
  echo "❌ Нет плагина docker compose (Compose V2)."
  echo "   Установите его: https://docs.docker.com/compose/install/"
  exit 1
fi

echo "========================================="
echo "Open WebUI + Neo4j + Uncensored AI Studio"
echo "========================================="
echo "🔧 Режим работы: онлайн"

# --- Очистка перед сборкой ---------------------------------------------------
echo "🧹 Останавливаем и удаляем старые контейнеры..."
docker compose --env-file "$ENV_FILE" down --remove-orphans || true

echo "🗑️  Удаляем старые образы этого проекта..."
# Удаляем только образы, созданные этим compose (не системные и не от других проектов)
docker images --format '{{.Repository}}:{{.Tag}}' | \
  grep -E '^open-webui|^open-webui-studio|^studio' | \
  xargs -r docker rmi -f 2>/dev/null || true

echo "🔌 Очищаем порты от зависших процессов..."
for _port in 8083 7687 7474 14200 10086; do
  # Find and kill processes using the port
  pids=$(lsof -ti ":${_port}" 2>/dev/null || true)
  if [[ -n "$pids" ]]; then
    echo "   Порт ${_port} занят PID(s) ${pids} — убиваем..."
    kill -9 $pids 2>/dev/null || true
  fi
done

# Отключаем BuildKit для использования классического сборщика Docker, который не пытается тянуть образы из сети
# Используем --pull=never, чтобы гарантировать использование только локальных слоёв и образов
# Убираем --no-cache, чтобы использовать кэш Docker
# Добавляем явное указание платформы
DOCKER_BUILDKIT=0 COMPOSE_DOCKER_CLI_BUILD=0 docker compose --env-file "$ENV_FILE" build --pull=false

# Затем запускаем контейнеры с пересобранными образами
docker compose --env-file "$ENV_FILE" up -d