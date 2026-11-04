#!/usr/bin/env python3

file_path = '/root/soft/open-webui-uncensored/src/lib/components/chat/Chat.svelte'

with open(file_path, 'r', encoding='utf-8') as file:
    content = file.read()

# Исправляем синтаксис функции sendMessageSocket
old_pattern = '''const sendMessageSocket = async (
    model: any
    _messages: any
    _history: any
    responseMessageId: any
    _chatId: any
    {'''
new_pattern = '''const sendMessageSocket = async (
    model: any,
    _messages: any,
    _history: any,
    responseMessageId: any,
    _chatId: any,
    {'''
content = content.replace(old_pattern, new_pattern)

with open(file_path, 'w', encoding='utf-8') as file:
    file.write(content)

print("Файл успешно исправлен.")