#!/usr/bin/env bash
set -euo pipefail

# ---------------------------------------------------------------------------
# Pull and run the official Ollama container with optional GPU support.
# ---------------------------------------------------------------------------

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

# Очистка Docker от старых контейнеров и образов
if command -v docker &> /dev/null; then
  echo "🧹 Очистка Docker..."
  docker stop ollama 2>/dev/null || true
  docker rm ollama 2>/dev/null || true
  docker system prune -f 2>/dev/null || true
fi

readonly CONTAINER="ollama"
readonly HOST_PORT="${OLLAMA_PORT:-11434}"
readonly CONTAINER_PORT=11434

clear_port "$HOST_PORT"

read -rp "Enable GPU passthrough? [y/N]: " use_gpu

echo "Pulling latest Ollama image..."
docker pull ollama/ollama:latest

echo "Stopping any existing ${CONTAINER} container..."
docker rm -f "$CONTAINER" 2>/dev/null || true

gpu_flags=()
if [[ "${use_gpu,,}" =~ ^y(es)?$ ]]; then
  gpu_flags=("--gpus=all")
  echo "GPU passthrough enabled."
fi

echo "Starting ${CONTAINER}..."
docker run -d \
  "${gpu_flags[@]}" \
  -v "ollama:/root/.ollama" \
  -p "${HOST_PORT}:${CONTAINER_PORT}" \
  --name "$CONTAINER" \
  ollama/ollama

echo "Cleaning up dangling images..."
docker image prune -f

echo "Ollama is running at http://localhost:${HOST_PORT}"
