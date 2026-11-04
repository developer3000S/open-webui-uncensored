#!/usr/bin/env python3

file_path = '/root/soft/open-webui-uncensored/src/lib/components/layout/Sidebar/UserMenu.svelte'

with open(file_path, 'r', encoding='utf-8') as file:
    content = file.read()

# Проверяем, есть ли </script> в конце файла
if '</script>' not in content:
    content += '\n</script>'

with open(file_path, 'w', encoding='utf-8') as file:
    file.write(content)

print("Файл успешно исправлен.")