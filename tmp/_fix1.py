import re

files = [
 'src/lib/components/admin/Settings/Database.svelte',
 'src/lib/components/channel/MessageInput.svelte',
 'src/lib/components/chat/FileNav.svelte',
 'src/lib/components/chat/MessageInput.svelte',
 'src/lib/components/common/RichTextInput.svelte',
 'src/lib/components/notes/NoteEditor.svelte',
 'src/lib/components/workspace/Knowledge/KnowledgeBase.svelte',
 'src/lib/components/workspace/Models/Knowledge.svelte',
 'src/lib/components/workspace/Models/PromptSuggestions.svelte',
 'src/lib/components/workspace/common/AccessControl.svelte',
 'src/lib/components/workspace/common/MemberSelector.svelte',
 'src/routes/(app)/workspace/prompts/create/+page.svelte',
 'src/routes/(app)/workspace/tools/create/+page.svelte',
]

for f in files:
    src = open(f).read()
    for m in re.finditer(r'<script([^>]*)>', src):
        attrs = m.group(1)
        end = src.find('</script>', m.end())
        body = src[m.end():end]
        has_ts = bool(re.search(r':\s*(any|string|number|boolean)\b', body)) or 'interface' in body or 'as const' in body
        lang_ts = 'lang="ts"' in attrs or "lang='ts'" in attrs
        if has_ts and not lang_ts:
            line = src[:m.start()].count('\n')+1
            print(f, 'script@'+str(line), 'attrs:', repr(attrs.strip()[:60]))
