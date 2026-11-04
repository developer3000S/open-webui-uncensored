#!/usr/bin/env python3

file_path = '/root/soft/open-webui-uncensored/src/lib/components/notes/NoteEditor.svelte'

with open(file_path, 'r', encoding='utf-8') as file:
    content = file.read()

# Исправляем использование forEach с async/await
content = content.replace('inputFiles.forEach((file: any) {\n        await inputFileHandler(file);\n      });', 'for (const file of inputFiles) {\n        await inputFileHandler(file);\n      }')

with open(file_path, 'w', encoding='utf-8') as file:
    file.write(content)

print("Файл успешно исправлен.")