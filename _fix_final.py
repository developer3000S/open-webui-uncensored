import re, sys

def patch(path, pairs):
    s = open(path).read()
    for old, new in pairs:
        if old not in s:
            print(f"MISS in {path}: {old[:70]!r}")
            continue
        s = s.replace(old, new, 1)
    open(path, 'w').write(s)
    print(f"OK {path}")

# 1. Chat.svelte — corrupted destructure param
patch('src/lib/components/chat/Chat.svelte', [
    ("(userPrompt: any { _raw = false } = {})", "(userPrompt: any, { _raw = false } = {})"),
])

# 2. NoteEditor.svelte — lost async in Promise executor
patch('src/lib/components/notes/NoteEditor.svelte', [
    ("new Promise((resolve: any, reject: any) => {", "new Promise(async (resolve: any, reject: any) => {"),
])

# 3. PromptSuggestions.svelte — lost async on reader.onload
patch('src/lib/components/workspace/Models/PromptSuggestions.svelte', [
    ("reader.onload = (event: any) {", "reader.onload = async (event: any) => {"),
])

# 4. KnowledgeBase.svelte — restore original function declaration
kb_pairs = []
s = open('src/lib/components/workspace/Knowledge/KnowledgeBase.svelte').read()
m = re.search(r'const traverse = async \(handle: FileSystemDirectoryHandle, dirPath: string = \'\'' , s)
if m:
    # find the matching end of arrow body: we replace conservatively by converting to function decl
    old_head = m.group(0) + ') {'
    new_head = "async function traverse(handle: FileSystemDirectoryHandle, dirPath = '') {"
    s = s.replace(old_head, new_head, 1)
    # remove trailing arrow terminator if present: find first '\t\t\t};' after position that closes it -> risky; instead check closing pattern
    open('src/lib/components/workspace/Knowledge/KnowledgeBase.svelte','w').write(s)
    print("KB patched head")
else:
    print("KB head MISS")

# 5. FileNav.svelte — subscribe callback needs async
patch('src/lib/components/chat/FileNav.svelte', [
    ("showFileNavPath.subscribe((filePath: any) => {", "showFileNavPath.subscribe(async (filePath: any) => {"),
])

# 6. MessageInput x2 — compressImageHandler needs async
for f in ['src/lib/components/chat/MessageInput.svelte', 'src/lib/components/channel/MessageInput.svelte']:
    patch(f, [
        ("const compressImageHandler = (imageUrl: any, settings: any = {}, config: any = {}) => {",
         "const compressImageHandler = async (imageUrl: any, settings: any = {}, config: any = {}) => {"),
    ])

# 7. UserMenu.svelte — remove duplicated trailing <svelte:window> block
f = 'src/lib/components/layout/Sidebar/UserMenu.svelte'
s = open(f).read()
dup = """
<svelte:window
\ton:keydown={(e) => {
\t\tif (e.key === 'Shift') shiftKey = true;
\t}}
\ton:keyup={(e) => {
\t\tif (e.key === 'Shift') shiftKey = false;
\t}}
/>
"""
idx_last = s.rfind('<svelte:window')
if idx_last != -1 and s.count('<svelte:window') == 2:
    # find start of preceding blank line before the dup tag
    start = s.rfind('\n\n<svelte:window')
    end = s.find('/>', idx_last) + len('/>')
    removed = s[start:end]
    s = s[:start] + s[end:]
    open(f,'w').write(s)
    print("UserMenu dup window removed, len:", len(removed))
else:
    print("UserMenu skip, count=", s.count('<svelte:window'))
