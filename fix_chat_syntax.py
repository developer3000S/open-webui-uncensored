#!/usr/bin/env python3

import re

file_path = '/root/soft/open-webui-uncensored/src/lib/components/chat/Chat.svelte'

with open(file_path, 'r', encoding='utf-8') as file:
    content = file.read()

# Исправляем синтаксис функции
content = re.sub(r'const sendMessageSocket = async \(\s*\n\s*model: any\s*\n\s*_messages: any\s*\n\s*_history: any\s*\n\s*responseMessageId: any\s*\n\s*_chatId: any\s*\n\s*\{', 'const sendMessageSocket = async (
	model: any,
	_messages: any,
	_history: any,
	responseMessageId: any,
	_chatId: any,
	{', content)

with open(file_path, 'w', encoding='utf-8') as file:
    file.write(content)

print("Файл успешно исправлен.")