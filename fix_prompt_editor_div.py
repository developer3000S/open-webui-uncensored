#!/usr/bin/env python3

import re

file_path = '/root/soft/open-webui-uncensored/src/lib/components/workspace/Prompts/PromptEditor.svelte'

with open(file_path, 'r', encoding='utf-8') as file:
    content = file.read()

# Удаляем лишний </div>
content = re.sub(r'\n\s*</div>\n\s*</div>', '', content)

with open(file_path, 'w', encoding='utf-8') as file:
    file.write(content)

print("Файл успешно исправлен.")