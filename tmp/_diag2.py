import re, subprocess, json

files = {
 'src/lib/components/channel/MessageInput.svelte': 351,
 'src/lib/components/chat/FileNav.svelte': 839,
 'src/lib/components/chat/MessageInput.svelte': 735,
 'src/lib/components/common/RichTextInput.svelte': 798,
 'src/lib/components/notes/NoteEditor.svelte': 563,
 'src/lib/components/workspace/Knowledge/KnowledgeBase.svelte': 606,
 'src/lib/components/workspace/Models/Knowledge.svelte': 105,
 'src/lib/components/workspace/Models/PromptSuggestions.svelte': 53,
 'src/lib/components/workspace/common/AccessControl.svelte': 307,
 'src/lib/components/workspace/common/MemberSelector.svelte': 89,
 'src/routes/(app)/workspace/prompts/create/+page.svelte': 37,
 'src/routes/(app)/workspace/tools/create/+page.svelte': 58,
}

for f, ln in files.items():
    src = open(f).read()
    # locate script blocks
    blocks = []
    for m in re.finditer(r'<script([^>]*)>', src):
        end = src.find('</script>', m.end())
        start_line = src[:m.end()].count('\n') + 1
        blocks.append((start_line, src[m.end():end], 'lang="ts"' in m.group(1)))
    lines = src.split('\n')
    print('='*10, f, 'err line', ln)
    ctx_start = max(0, ln-6)
    for j in range(ctx_start, min(len(lines), ln+4)):
        print(j+1, '|', lines[j][:150])
