#!/usr/bin/env python3

import re

file_path = '/root/soft/open-webui-uncensored/src/lib/components/layout/Sidebar/UserMenu.svelte'

with open(file_path, 'r', encoding='utf-8') as file:
    content = file.read()

# Удаляем обработчики событий в конце файла
content = re.sub(r'on:keydown=\{.*?\}.+?on:keyup=\{.*?\}>', '', content, flags=re.DOTALL)

with open(file_path, 'w', encoding='utf-8') as file:
    file.write(content)

print("Файл успешно исправлен.")