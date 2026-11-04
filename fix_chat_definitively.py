#!/usr/bin/env python3

file_path = '/root/soft/open-webui-uncensored/src/lib/components/chat/Chat.svelte'

with open(file_path, 'r', encoding='utf-8') as file:
    lines = file.readlines()

# Находим строку с ошибкой и исправляем её
for i, line in enumerate(lines):
    if 'sendMessageSocket = async (' in line and 'model: any' in line and '_messages: any' in line:
        lines[i] = '    const sendMessageSocket = async (model: any, _messages: any, _history: any, responseMessageId: any, _chatId: any, {\n'

with open(file_path, 'w', encoding='utf-8') as file:
    file.writelines(lines)

print("Файл успешно исправлен.")