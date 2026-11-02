#!/usr/bin/env python3

import re

file_path = '/root/soft/open-webui-uncensored/src/lib/components/chat/FileNav/FilePreview.svelte'

# Чтение файла
with open(file_path, 'r', encoding='utf-8') as file:
    content = file.read()

# Добавление импорта для HTML типов
content = re.sub(r'<script lang=\"ts\">', '<script lang="ts">\nimport type { HTMLTextAreaElement, HTMLDivElement } from \"svelte/elements\"', content)

# Замена переменных
content = re.sub(r'let\s+pdfViewerRef: PDFViewer;', 'let _pdfViewerRef: PDFViewer;', content)
content = re.sub(r'let\s+fileCodeEditorRef: FileCodeEditor;', 'let _fileCodeEditorRef: FileCodeEditor;', content)

# Замена использования переменных
content = re.sub(r'pdfViewerRef\.resetView\(\)', '_pdfViewerRef?.resetView()', content)
content = re.sub(r'fileCodeEditorRef\.getValue\(\)', '_fileCodeEditorRef?.getValue()', content)

# Удаление неиспользуемых переменных
content = re.sub(r'let\s+parsedJson: unknown = undefined;\s*parsedJson = undefined;', '', content)
content = re.sub(r'let\s+jsonError: string \| null = null;\s*jsonError = null;', '', content)
content = re.sub(r'let\s+parsedNotebook: Record<string, unknown> \| null = null;\s*parsedNotebook = null;', '', content)
content = re.sub(r'let\s+highlightedHtml: string \| null = null;\s*highlightedHtml = null;', '', content)

# Запись измененного содержимого обратно в файл
with open(file_path, 'w', encoding='utf-8') as file:
    file.write(content)

print("Файл успешно отредактирован!")