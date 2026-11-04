#!/usr/bin/env python3

file_path = '/root/soft/open-webui-uncensored/src/lib/components/layout/Sidebar/UserMenu.svelte'

with open(file_path, 'r', encoding='utf-8') as file:
    content = file.read()

# Удаляем <svelte:window> из <script>
content = content.replace('<svelte:window\n    on:keydown=\n    (e) => {\n        if (e.key === \'Shift\') shiftKey = true;\n    }\n    on:keyup=\n    (e) => {\n        if (e.key === \'Shift\') shiftKey = false;\n    }\n/>', '')

# Добавляем <svelte:window> после </script>
content = content.replace('</script>', '</script>\n\n<svelte:window\n    on:keydown=\n    (e) => {\n        if (e.key === \'Shift\') shiftKey = true;\n    }\n    on:keyup=\n    (e) => {\n        if (e.key === \'Shift\') shiftKey = false;\n    }\n/>')

with open(file_path, 'w', encoding='utf-8') as file:
    file.write(content)

print("Файл успешно исправлен.")