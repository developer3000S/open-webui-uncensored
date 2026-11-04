#!/usr/bin/env python3

file_path = '/root/soft/open-webui-uncensored/src/lib/components/notes/NoteEditor.svelte'

with open(file_path, 'r', encoding='utf-8') as file:
    content = file.read()

# Исправляем использование await в NoteEditor.svelte
content = content.replace('const fileToRead = file[\'type\'] === \'image/heic\' ? await convertHeicToJpeg(file) : file;', 'let fileToRead;\n    if (file[\'type\'] === \'image/heic\') {\n        fileToRead = await convertHeicToJpeg(file);\n    } else {\n        fileToRead = file;\n    }\n    reader.readAsDataURL(fileToRead);')

with open(file_path, 'w', encoding='utf-8') as file:
    file.write(content)

print("Файл успешно исправлен.")