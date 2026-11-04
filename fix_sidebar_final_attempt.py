#!/usr/bin/env python3

file_path = '/root/soft/open-webui-uncensored/src/lib/components/layout/Sidebar.svelte'

with open(file_path, 'r', encoding='utf-8') as file:
    content = file.read()

# Заменяем строку с ошибкой
content = content.replace('$: if (isCoderRoute && $showSidebar) {\n    showSidebar.set(false);', '$: if (isCoderRoute && $showSidebar) showSidebar.set(false);')

with open(file_path, 'w', encoding='utf-8') as file:
    file.write(content)

print("Файл успешно исправлен.")