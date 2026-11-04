#!/usr/bin/env python3

import re

file_path = '/root/soft/open-webui-uncensored/src/lib/components/workspace/Knowledge/KnowledgeBase.svelte'

with open(file_path, 'r', encoding='utf-8') as file:
    content = file.read()

# Исправляем синтаксис функции traverse
content = re.sub(r'const traverse = async \(handle: FileSystemDirectoryHandle, dirPath: string = \'\'\'\s*\{\s*\n\s*for await', 'const traverse = async (handle: FileSystemDirectoryHandle, dirPath: string = "") => {\n                    for await', content)

with open(file_path, 'w', encoding='utf-8') as file:
    file.write(content)

print("Файл успешно исправлен.")