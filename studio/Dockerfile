# Uncensored AI Studio — сервисный образ.
# Используем локально доступный образ Node.js для корректной работы.
FROM dockerhub.timeweb.cloud/node:24.12.0-alpine

# Pin exact npm version for this image
RUN npm install -g npm@12.2.1 && node -v && npm -v

# Устанавливаем необходимые системные зависимости
RUN apk add --no-cache --update \
    libgomp \
    libsamplerate \
    sqlite \
    ca-certificates \
    curl \
    bash \
    && rm -rf /var/cache/apk/*

# Проверяем, что Node.js доступен в PATH
RUN echo "PATH: $PATH" && \
    which node && \
    node --version && npm --version

# Устанавливаем дополнительные зависимости, если они необходимы
RUN apk add --no-cache --virtual .build-deps \
    build-base \
    && rm -rf /var/cache/apk/*

# /app = studio/ на хосте. linux.sh и serve.cjs отсчитывают пути от своего
# расположжения: SCRIPT_DIR=/app, APP_DIR=/app/app, ROOT=/app — поэтому весь
# studio/ монтируется в /app одним куском, а не только app/. COPY не нужен:
# всё содержимое приходит bind mount'ом.
WORKDIR /app

# Тест, что бинарники живы на старте: если bind mount отвалился, падаем
# громко и сразу, а не mysterious "model not found" посреди работы.
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=2 \
    CMD curl -sf http://127.0.0.1:${FRONTEND_PORT:-14200}/api/health >/dev/null || exit 1

# Устанавливаем необходимые зависимости
RUN apk add --no-cache --update \
    libgomp \
    libsamplerate \
    sqlite \
    ca-certificates \
    curl \
    bash \
    && rm -rf /var/cache/apk/*

# Устанавливаем рабочую директорию
WORKDIR /app

# Копируем все необходимые файлы из текущей директории
COPY . /app/

# Устанавливаем права на исполнение для linux.sh
RUN chmod +x /app/linux.sh

# linux.sh — точка входа: он запускает serve.cjs портабельным node из app/tools.
CMD ["bash", "/app/linux.sh"]
