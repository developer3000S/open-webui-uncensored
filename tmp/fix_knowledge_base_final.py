#!/usr/bin/env python3

file_path = '/root/soft/open-webui-uncensored/src/lib/components/workspace/Knowledge/KnowledgeBase.svelte'

with open(file_path, 'r', encoding='utf-8') as file:
    content = file.read()

# Исправляем синтаксис функции traverse
content = content.replace('const traverse = async (handle: FileSystemDirectoryHandle, dirPath: string = \'\'\'\'\s*\{', 'const traverse = async (handle: FileSystemDirectoryHandle, dirPath: string = \'\'\') => {\n                    ')

with open(file_path, 'w', encoding='utf-8') as file:
    file.write(content)

print("Файл успешно исправлен.")