#!/usr/bin/env python3

file_path = '/root/soft/open-webui-uncensored/src/lib/components/chat/Chat.svelte'

with open(file_path, 'r', encoding='utf-8') as file:
    content = file.read()

# Заменяем строку с ошибкой
content = content.replace('const sendMessageSocket = async (\n    model: any\n    _messages: any\n    _history: any\n    responseMessageId: any\n    _chatId: any\n    {', 'const sendMessageSocket = async (
    model: any,
    _messages: any,
    _history: any,
    responseMessageId: any,
    _chatId: any,
    {')

with open(file_path, 'w', encoding='utf-8') as file:
    file.write(content)

print("Файл успешно исправлен.")