#!/usr/bin/env python3

file_path = '/root/soft/open-webui-uncensored/src/lib/components/chat/Chat.svelte'

with open(file_path, 'r', encoding='utf-8') as file:
    lines = file.readlines()

# Находим и исправляем строку с ошибкой
for i, line in enumerate(lines):
    if 'sendMessageSocket = async (' in line and 'model: any' in line and '_messages: any' in line:
        lines[i] = '    const sendMessageSocket = async (\n'
        lines[i+1] = '        model: any,\n'
        lines[i+2] = '        _messages: any,\n'
        lines[i+3] = '        _history: any,\n'
        lines[i+4] = '        responseMessageId: any,\n'
        lines[i+5] = '        _chatId: any,\n'
        lines[i+6] = '        {\n'

with open(file_path, 'w', encoding='utf-8') as file:
    file.writelines(lines)

print("Файл успешно исправлен.")