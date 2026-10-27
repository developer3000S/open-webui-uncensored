#!/usr/bin/env bash
set -euo pipefail

# Скрипт для создания Docker volumes для open-webui-uncensored
# ВНИМАНИЕ: Если volumes уже существуют, их данные будут уничтожены!

VOLUME_1="open-webui-rus_open-webui"
VOLUME_2="open-webui-rus_neo4j-data"

echo "========================================="
echo "Создание Docker volumes для Open WebUI"
echo "========================================="

# Функция проверки существования volume
volume_exists() {
    docker volume inspect "$1" &>/dev/null
}

# Функция удаления volume
remove_volume() {
    local vol="$1"
    echo "Удаление volume '$vol'..."
    docker volume rm "$vol" || {
        echo "❌ Ошибка при удалении volume '$vol'"
        return 1
    }
}

# Создание volume
create_volume() {
    local vol="$1"
    echo "Создание volume '$vol'..."
    docker volume create "$vol" || {
        echo "❌ Ошибка при создании volume '$vol'"
        return 1
    }
}

# Проверка существования обоих volumes
EXISTS_1=false
EXISTS_2=false

if volume_exists "$VOLUME_1"; then
    EXISTS_1=true
fi

if volume_exists "$VOLUME_2"; then
    EXISTS_2=true
fi

if [[ "$EXISTS_1" == true || "$EXISTS_2" == true ]]; then
    echo ""
    echo "⚠️  ВНИМАНИЕ: Найден(ы) существующий(ие) volume(ы):"
    [[ "$EXISTS_1" == true ]] && echo "  - $VOLUME_1"
    [[ "$EXISTS_2" == true ]] && echo "  - $VOLUME_2"
    echo ""
    echo "⚠️  ПРЕДУПРЕЖДЕНИЕ: При удалении существующих volumes все хранящиеся в них данные будут безвозвратно уничтожены!"
    echo "  Это может включать базы данных, конфигурации и другие пользовательские данные."
    echo ""
    read -p "Продолжить удаление и создание volumes? (введите 'yes' для подтверждения): " confirm
    if [[ "$confirm" != "yes" ]]; then
        echo "❌ Отменено пользователем."
        exit 1
    fi

    echo ""
    if [[ "$EXISTS_1" == true ]]; then
        remove_volume "$VOLUME_1"
    fi
    if [[ "$EXISTS_2" == true ]]; then
        remove_volume "$VOLUME_2"
    fi
else
    if [[ "$EXISTS_1" == false && "$EXISTS_2" == false ]]; then
        echo "Существующие volumes не найдены. Создаем новые."
    fi
fi

echo ""
create_volume "$VOLUME_1"
create_volume "$VOLUME_2"

echo ""
echo "✅ Готово! Volumes успешно созданы:"
docker volume ls | grep -E "$VOLUME_1|$VOLUME_2" || true
echo ""
echo "Теперь можно запускать docker-run.sh"
