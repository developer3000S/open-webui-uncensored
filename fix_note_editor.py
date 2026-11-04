#!/usr/bin/env python3

file_path = '/root/soft/open-webui-uncensored/src/lib/components/notes/NoteEditor.svelte'

with open(file_path, 'r', encoding='utf-8') as file:
    content = file.read()

# Исправляем использование await в NoteEditor.svelte
content = content.replace('reader.readAsDataURL(await (file[\'type\'] === \'image/heic\' ? convertHeicToJpeg(file) : Promise.resolve(file)));', '{\n    const fileToRead = file[\'type\'] === \'image/heic\' ? await convertHeicToJpeg(file) : file;\n    reader.readAsDataURL(fileToRead);\n}')

with open(file_path, 'w', encoding='utf-8') as file:
    file.write(content)

print("Файл успешно исправлен.")