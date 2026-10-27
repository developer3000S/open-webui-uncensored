#!/usr/bin/env bash
set -euo pipefail

# ---------------------------------------------------------------------------
# Запуск Open WebUI через Docker Compose
# ---------------------------------------------------------------------------

# Проверяем доступность docker-compose
if ! command -v docker-compose &> /dev/null; then
    echo "❌ docker-compose не найден. Используем стандартный docker..."
    if ! command -v docker &> /dev/null; then
        echo "❌ Docker не установлен"
        exit 1
    fi
    # Запускаем через docker-compose plugin
    DOCKER_COMPOSE_CMD="docker compose"
else
    DOCKER_COMPOSE_CMD="docker-compose"
fi

readonly HOST_PORT="${OPEN_WEBUI_PORT:-8083}"

# Очистка используемых портов (освобождаем только процессы, слушающие порт)
clear_port() {
  local port=$1
  if command -v fuser &> /dev/null; then
    if fuser "$port/tcp" &> /dev/null 2>&1; then
      echo "⚠️  Порт $port уже используется. Освобождаем..."
      fuser -k "$port/tcp" 2>/dev/null || echo "Не удалось освободить порт $port"
    fi
  elif command -v lsof &> /dev/null; then
    if lsof -i :"$port" &> /dev/null 2>&1; then
      echo "⚠️  Порт $port уже используется. Освобождаем..."
      local pids
      pids=$(lsof -t -i :"$port" 2>/dev/null || true)
      if [[ -n "$pids" ]]; then
        kill $pids 2>/dev/null || echo "Не удалось освободить порт $port"
      fi
    fi
  fi
}

echo "========================================="
echo "Open WebUI Docker Compose Runner"
echo "========================================="

echo "🧹 Очистка старых контейнеров..."
$DOCKER_COMPOSE_CMD down --remove-orphans 2>/dev/null || true
docker system prune -f 2>/dev/null || true

clear_port "$HOST_PORT"

echo "🔨 Сборка и запуск контейнеров..."
if ! $DOCKER_COMPOSE_CMD up -d --build; then
    echo "❌ Ошибка запуска docker-compose"
    exit 1
fi

echo "⏳ Ожидание запуска контейнера..."
sleep 5

echo "📋 Проверка состояния..."
if ! $DOCKER_COMPOSE_CMD ps; then
    echo "⚠️  Не удалось получить статус контейнеров"
fi

echo ""
echo "✅ Open WebUI запущен через Docker Compose!"
echo ""
echo "🌐 Доступен по адресу: http://localhost:${HOST_PORT}"
echo "📁 Данные сохраняются в томе: open-webui"
echo ""
echo "📋 Полезные команды:"
echo "   $DOCKER_COMPOSE_CMD logs          - просмотр логов"
echo "   $DOCKER_COMPOSE_CMD ps            - статус контейнеров"
echo "   $DOCKER_COMPOSE_CMD down          - остановить и удалить контейнеры"
echo "   $DOCKER_COMPOSE_CMD restart       - перезапустить контейнеры"
echo "   docker exec -it open-webui bash  - войти в контейнер"
echo "========================================="