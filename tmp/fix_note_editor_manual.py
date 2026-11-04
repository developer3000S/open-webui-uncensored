#!/usr/bin/env python3

file_path = '/root/soft/open-webui-uncensored/src/lib/components/notes/NoteEditor.svelte'

with open(file_path, 'r', encoding='utf-8') as file:
    content = file.read()

# Исправляем использование await в NoteEditor.svelte
content = content.replace('fileToRead = await convertHeicToJpeg(file);', 'fileToRead = convertHeicToJpeg(file);')

# Обновляем reader.onload для async/await
content = content.replace('reader.onload = async (event: ProgressEvent<FileReader>) => {\n                    try {\n                        let imageUrl = event.target.result;\n                        imageUrl = await compressImageHandler(imageUrl, $settings, $config);', 'reader.onload = async (event: ProgressEvent<FileReader>) => {\n                    try {\n                        let imageUrl = event.target.result;\n                        imageUrl = await compressImageHandler(imageUrl, $settings, $config);\n                        const fileToRead = file[\'type\'] === \'image/heic\' ? await convertHeicToJpeg(file) : file;\n                        reader.readAsDataURL(fileToRead);\n                        return;')

with open(file_path, 'w', encoding='utf-8') as file:
    file.write(content)

print("Файл успешно исправлен.")