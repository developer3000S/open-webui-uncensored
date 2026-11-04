#!/usr/bin/env python3

file_path = '/root/soft/open-webui-uncensored/src/lib/components/chat/Chat.svelte'

with open(file_path, 'r', encoding='utf-8') as file:
    content = file.readlines()

# Находим и исправляем строку с ошибкой
for i, line in enumerate(content):
    if 'sendMessageSocket = async (' in line and 'model: any' in line:
        content[i] = '    const sendMessageSocket = async (\n'
        content[i+1] = '        model: any,\n'
        content[i+2] = '        _messages: any,\n'
        content[i+3] = '        _history: any,\n'
        content[i+4] = '        responseMessageId: any,\n'
        content[i+5] = '        _chatId: any,\n'
        content[i+6] = '        {\n'

with open(file_path, 'w', encoding='utf-8') as file:
    file.writelines(content)

print("Файл успешно исправлен.")