# Инструкция по установке и запуску Open WebUI в офлайн-режиме

Этот документ описывает процесс скачивания всех необходимых зависимостей на машине с доступом в интернет и последующей установки и запуска Open WebUI на машине без интернета.


## Требования

- Машина с доступом в интернет для скачивания зависимостей
- Машина без интернета для установки и запуска
- Docker и Docker Compose (для контейнерного варианта)
- Python 3.11 и выше
- Node.js и npm (для фронтенда)


## Часть 1: Скачивание зависимостей на машине с интернетом

### 1.1 Создание директории для пакетов

Создайте директорию для хранения всех локальных пакетов:

```bash
mkdir -p ~/openwebui_offline_packages
cd ~/openwebui_offline_packages
```

### 1.2 Скачивание Python-пакетов

Скачайте все необходимые Python-пакеты с помощью `pip download`:

```bash
pip download torch==2.9.1+cpu torchvision torchaudio sentence-transformers faster-whisper tiktoken nltk uv chromadb aiosqlite psycopg2-binary alembic pycrdt redis python-dotenv --no-cache-dir -d .
```

Если у вас есть файл `requirements_clean.txt`, используйте его для скачивания всех зависимостей:

```bash
pip download -r /путь/к/open-webui-uncensored/backend/requirements_clean.txt --no-cache-dir -d .
```

### 1.3 Скачивание дополнительных пакетов

Убедитесь, что у вас есть все необходимые пакеты для работы с PDF и OCR:

```bash
pip download pytesseract pdf2image --no-cache-dir -d .
```

### 1.4 Скачивание фронтенд-зависимостей

Если вам нужен фронтенд, перейдите в директорию проекта и установите зависимости для Node.js:

```bash
cd /путь/к/open-webui-uncensored
npm install --production --omit=dev
```

Эта команда сохранит все зависимости в папке `node_modules`.


## Часть 2: Перенос пакетов на целевую машину

Скопируйте все скачанные пакеты на целевую машину без интернета:

```bash
# Копирование Python-пакетов
scp -r ~/openwebui_offline_packages/* пользователь@целевой_адрес:/путь/на/целевой/машине/openwebui_local_packages/

# Копирование node_modules (если нужно)
scp -r /путь/к/open-webui-uncensored/node_modules пользователь@целевой_адрес:/путь/на/целевой/машине/open-webui-uncensored/

# Копирование самого проекта (если еще не скопирован)
scp -r /путь/к/open-webui-uncensored пользователь@целевой_адрес:/путь/на/целевой/машине/
```


## Часть 3: Установка и запуск на целевой машине

### 3.1 Установка Docker и Docker Compose (если используется контейнерный вариант)

Убедитесь, что Docker и Docker Compose установлены на целевой машине:

```bash
# Для Debian/Ubuntu
sudo apt-get update
sudo apt-get install -y docker.io docker-compose
sudo systemctl enable --now docker
sudo usermod -aG docker $USER
newgrp docker  # Перезагрузить группу пользователя
```


### 3.2 Создание Dockerfile для офлайн-сборки

Создайте файл `Dockerfile.offline` в корне проекта:

```dockerfile
# syntax=docker/dockerfile:1

FROM python:3.11-slim

# Устанавливаем системные зависимости
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    git \
    curl \
    jq \
    ca-certificates \
    libmariadb-dev \
    python3-dev \
    ffmpeg \
    libsm6 \
    libxext6 \
    zstd \
    tesseract-ocr \
    tesseract-ocr-rus \
    tesseract-ocr-eng \
    poppler-utils \
    build-essential && \
    rm -rf /var/lib/apt/lists/*

# Копируем локальные пакеты и устанавливаем их
COPY openwebui_local_packages/ /tmp/local_packages/
RUN pip install --no-cache-dir /tmp/local_packages/*.whl && \
    rm -rf /tmp/local_packages

# Копируем и устанавливаем остальные зависимости
WORKDIR /app/backend
COPY backend/requirements_clean.txt .
RUN pip install --no-cache-dir -r requirements_clean.txt

# Копируем остальные файлы проекта
COPY --chown=1000:1000 . .

# Создаем директории для кэша
RUN mkdir -p /app/backend/data/cache/whisper/models \
    /app/backend/data/cache/embedding/models \
    /app/backend/data/cache/tiktoken

# Устанавливаем переменные окружения
ENV PYTHONUNBUFFERED=1 \
    HOME=/root \
    WHISPER_MODEL_DIR=/app/backend/data/cache/whisper/models \
    SENTENCE_TRANSFORMERS_HOME=/app/backend/data/cache/embedding/models \
    TIKTOKEN_CACHE_DIR=/app/backend/data/cache/tiktoken \
    HF_HOME=/app/backend/data/cache/embedding/models \
    SCARF_NO_ANALYTICS=true \
    DO_NOT_TRACK=true \
    ANONYMIZED_TELEMETRY=false \
    USE_CUDA=false \
    USE_SLIM=true \
    WEBUI_SECRET_KEY=test-secret-key

CMD ["bash", "start.sh"]
```


### 3.3 Создание docker-compose.offline.yml

Создайте файл `docker-compose.offline.yml` для запуска контейнеров:

```yaml
version: '3.8'

services:
  open-webui:
    build:
      context: .
      dockerfile: Dockerfile.offline
    ports:
      - "8080:8080"
    environment:
      - WEBUI_SECRET_KEY=test-secret-key
    volumes:
      - ./backend:/app/backend
      - ./data:/app/backend/data
    networks:
      - open-webui-network

networks:
  open-webui-network:
    driver: bridge
```


### 3.4 Сборка и запуск Docker-контейнера

Перейдите в директорию с проектом и соберите Docker-образ:

```bash
cd /путь/к/open-webui-uncensored
docker-compose -f docker-compose.offline.yml build
```

Запустите контейнер:

```bash
docker-compose -f docker-compose.offline.yml up -d
```


## Часть 4: Локальный запуск без Docker (альтернативный вариант)

Если вы не хотите использовать Docker, можете запустить Open WebUI напрямую:

### 4.1 Создание виртуального окружения

```bash
cd /путь/к/open-webui-uncensored
python3 -m venv venv
source venv/bin/activate
```

### 4.2 Установка локальных пакетов

```bash
pip install /путь/к/openwebui_local_packages/*.whl
pip install -r backend/requirements_clean.txt
```

### 4.3 Запуск бэкенда

```bash
export WEBUI_SECRET_KEY=$(openssl rand -hex 32)
python -m backend.main --host 0.0.0.0 --port 8080
```

### 4.4 Запуск фронтенда

Если вам нужен фронтенд, сначала соберите его:

```bash
cd /путь/к/open-webui-uncensored
npm install
npm run build
```

Затем запустите фронтенд с помощью Vite:

```bash
npm run dev
```

Фронтенд будет доступен по адресу `http://localhost:5173`.


## Часть 5: Настройка прокси между фронтендом и бэкендом

Если вы запускаете фронтенд и бэкенд на разных портах, можно настроить прокси с помощью Nginx или использовать инструменты, такие как `locust` или `nginx-proxy`.

Пример конфигурации Nginx (`/etc/nginx/sites-available/openwebui`):

```nginx
server {
    listen 80;
    server_name localhost;

    location / {
        proxy_pass http://localhost:5173;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    }

    location /api/ {
        proxy_pass http://localhost:8080;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    }
}
```

После настройки Nginx, не забудьте его перезапустить:

```bash
sudo systemctl restart nginx
```


## Часть 6: Решение типичных проблем

### 6.1 Ошибки при установке PyTorch

Если возникают ошибки при установке PyTorch, убедитесь, что вы используете версию для CPU:

```bash
pip install torch==2.9.1+cpu torchvision torchaudio
```

### 6.2 Отсутствие зависимостей для OCR

Убедитесь, что установлены все необходимые системные зависимости для OCR:

```bash
sudo apt-get install -y tesseract-ocr tesseract-ocr-rus tesseract-ocr-eng poppler-utils
```

### 6.3 Проблемы с переменной WEBUI_SECRET_KEY

Убедитесь, что переменная `WEBUI_SECRET_KEY` установлена перед запуском:

```bash
export WEBUI_SECRET_KEY=$(openssl rand -hex 32)
```


## Заключение

Следуя этой инструкции, вы сможете:
1. Скачать все необходимые зависимости на машине с интернетом
2. Перенести их на целевую машину без интернета
3. Установить и запустить Open WebUI как в Docker-контейнере, так и напрямую

Это позволит вам работать с Open WebUI в офлайн-режиме без необходимости подключения к интернету для установки зависимостей.