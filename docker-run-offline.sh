#!/usr/bin/env bash
set -euo pipefail

# ---------------------------------------------------------------------------
# Поднимает стек целиком: open-webui, Neo4j и Uncensored AI Studio.
# Офлайн-режим: использует локальные зависимости и не требует доступа в интернет.
#
# Конфигурация контейнеров живёт в docker-compose.offline.yaml — тома, общая сеть,
# порты и healthcheck описаны в одном месте, а не дублируются здесь.
# Параметры сборки/запуска (порты, пароль Neo4j, upstream студии) берутся
# из .env; compose читает его сам.
#
# Поддержка офлайн-режима:
#   - Использует Dockerfile.offline для сборки
#   - Локальные зависимости должны быть предварительно скачаны и скопированы
# ---------------------------------------------------------------------------

REPO_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &>/dev/null && pwd)"
readonly REPO_DIR
ENV_FILE="${REPO_DIR}/.env"
readonly ENV_FILE

# Пути к офлайн-конфигурации
OFFLINE_COMPOSE_FILE="${REPO_DIR}/docker-compose.offline.yaml"
OFFLINE_DOCKERFILE="${REPO_DIR}/Dockerfile.offline"
readonly OFFLINE_COMPOSE_FILE OFFLINE_DOCKERFILE

# Проверка наличия файла .env
if [[ ! -f "$ENV_FILE" ]]; then
  echo "❌ Не найден ${ENV_FILE}"
  echo "   Скопируйте шаблон и заполните: cp ${REPO_DIR}/.env.example ${ENV_FILE}"
  exit 1
fi

# Проверка наличия OLLAMA_BASE_URL
if ! grep -Eq "^[[[:space:]]]*(export[[[:space:]]]+)?OLLAMA_BASE_URL[[[:space:]]]*=[[:space:]]*['"?]https?://" "$ENV_FILE"; then
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
echo "Open WebUI + Neo4j"
echo "========================================="
echo "🔧 Режим работы: офлайн"

# --- Проверка наличия офлайн-конфигурации ---
if [[ ! -f "$OFFLINE_COMPOSE_FILE" || ! -f "$OFFLINE_DOCKERFILE" ]]; then
  echo "❌ Ошибка: для офлайн-режима требуются файлы:"
  echo "   - $OFFLINE_COMPOSE_FILE"
  echo "   - $OFFLINE_DOCKERFILE"
  echo "   Пожалуйста, убедитесь, что они доступны."
  exit 1
fi

# --- Проверка наличия локальных пакетов ---
LOCAL_PACKAGES_DIR="${REPO_DIR}/openwebui_offline_packages"
if [[ ! -d "$LOCAL_PACKAGES_DIR" ]]; then
  echo "❌ В офлайн-режиме не найдена директория с локальными пакетами: $LOCAL_PACKAGES_DIR"
  echo "   Пожалуйста, скачайте зависимости согласно INSTALL_OFFLINE.md"
  exit 1
fi
echo "✅ Директория с локальными пакетами найдена: $LOCAL_PACKAGES_DIR"

# --- Проверка наличия requirements.txt ---
REQUIREMENTS_FILE="${REPO_DIR}/backend/requirements.txt"
if [[ ! -f "$REQUIREMENTS_FILE" ]]; then
  echo "❌ Не найден файл $REQUIREMENTS_FILE"
  echo "   Пожалуйста, убедитесь, что файл requirements.txt доступен в директории backend."
  exit 1
fi

# --- Очистка перед сборкой ---------------------------------------------------
echo "🧹 Останавливаем и удаляем старые контейнеры..."
docker compose -f "$OFFLINE_COMPOSE_FILE" --env-file "$ENV_FILE" down --remove-orphans || true

echo "🗑️  Удаляем старые образы этого проекта..."
# Удаляем только образы, созданные этим compose (не системные и не от других проектов)
docker images --format '{{.Repository}}:{{.Tag}}' | \
  grep -E '^open-webui|^neo4j' | \
  xargs -r docker rmi -f 2>/dev/null || true

echo "🔌 Очищаем порты от зависших процессов..."
for _port in 8080 7687 7474; do
  pid=$(lsof -ti ":${_port}" 2>/dev/null || true)
  if [[ -n "$pid" ]]; then
    echo "   Порт ${_port} занят PID ${pid} — убиваем..."
    kill -9 "$pid" 2>/dev/null || true
  fi
done

# Отключаем BuildKit для использования классического сборщика Docker
# Используем --pull=never, чтобы гарантировать использование только локальных слоёв
DOCKER_BUILDKIT=0 COMPOSE_DOCKER_CLI_BUILD=0 docker compose -f "$OFFLINE_COMPOSE_FILE" --env-file "$ENV_FILE" build --pull=false

# Затем запускаем контейнеры с пересобранными образами
docker compose -f "$OFFLINE_COMPOSE_FILE" --env-file "$ENV_FILE" up -d