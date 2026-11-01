#!/bin/bash

# Запускаем Docker-контейнер с нужной версией Node.js
# и обновляем зависимости

docker run --rm -it -v $(pwd):/app -w /app node:24.22.2 bash -c "
  # Устанавливаем зависимости
  npm install --legacy-peer-deps && 
  # Пытаемся обновить уязвимые пакеты
  npm audit fix --force && 
  # Если не получилось, обновляем вручную
  npm install <(npm audit --json | jq -r '.metadata.vulnerabilities[] | select(.severity == "high" or .severity == "critical") | .name')@latest
"