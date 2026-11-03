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
        lang_ts = 'lang="ts"' in attrs or "lang='ts'" in attrs
        line = src[:m.start()].count('\n')+1
        print('FILE:', f, 'script@'+str(line), 'attrs:', repr(attrs.strip()[:50]), 'body_len:', len(body))
