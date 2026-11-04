#!/usr/bin/env python3

file_path = '/root/soft/open-webui-uncensored/src/lib/components/layout/Sidebar/UserMenu.svelte'

with open(file_path, 'r', encoding='utf-8') as file:
    content = file.read()

# Удаляем <svelte:window> из <script>
content = content.replace('<svelte:window\n    on:keydown=\{.*?\}\n    on:keyup=\{.*?\}>', '')

# Добавляем <svelte:window> после закрытия <script>
window_tag = '''<svelte:window\n    on:keydown=\n    (e) => {\n        if (e.key === \'Shift\') shiftKey = true;\n    }\n    on:keyup=\n    (e) => {\n        if (e.key === \'Shift\') shiftKey = false;\n    }\n/>'''
content = content.replace('</script>', '</script>\n' + window_tag)

with open(file_path, 'w', encoding='utf-8') as file:
    file.write(content)

print("Файл успешно исправлен.")