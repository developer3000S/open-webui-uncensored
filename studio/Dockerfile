# Uncensored AI Studio — сервисный образ.
# Вся runtime-логика и бинарники (node, llama-server, whisper, sd-server, Kokoro)
# уже установлены в studio/app на хосте и пробрасываются целиком через bind
# mount — внутри контейнера ничего не пересобирается.
FROM node:22-bookworm

# Бэкендам студии нужны libsamplerate0 (whisper) и libgomp1 (ggml/OpenBLAS);
# sqlite3 — serve.cjs выполняет им миграции/запросы к studio.db; curl —
# HEALTHCHECK. Всё остальное разрешается системными библиотеками Debian.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libgomp1 \
        libsamplerate0 \
        sqlite3 \
        ca-certificates \
        curl \
    && rm -rf /var/lib/apt/lists/*

# /app = studio/ на хосте. linux.sh и serve.cjs отсчитывают пути от своего
# расположения: SCRIPT_DIR=/app, APP_DIR=/app/app, ROOT=/app — поэтому весь
# studio/ монтируется в /app одним куском, а не только app/. COPY не нужен:
# всё содержимое приходит bind mount'ом.
WORKDIR /app

# Тест, что бинарники живы на старте: если bind mount отвалился, падаем
# громко и сразу, а не mysterious "model not found" посреди работы.
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=2 \
    CMD curl -sf http://127.0.0.1:${FRONTEND_PORT:-14200}/api/health >/dev/null || exit 1

# linux.sh — точка входа: он запускает serve.cjs портабельным node из app/tools.
# read -rp в linux.sh получает EOF из неинтерактивного контекста и продолжает.
CMD [ "bash", "/app/linux.sh" ]
