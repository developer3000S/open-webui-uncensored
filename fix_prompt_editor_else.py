#!/usr/bin/env python3

file_path = '/root/soft/open-webui-uncensored/src/lib/components/workspace/Prompts/PromptEditor.svelte'

with open(file_path, 'r', encoding='utf-8') as file:
    content = file.read()

# Заменяем некорректное использование {:else} на {#if}
content = content.replace('{:else}', '{#if false}')

with open(file_path, 'w', encoding='utf-8') as file:
    file.write(content)

print("Файл успешно исправлен.")