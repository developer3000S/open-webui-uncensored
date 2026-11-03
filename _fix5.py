import re

def rd(f): return open(f).read()
def wr(f,s): open(f,'w').write(s)

# 1. forEach((x: any) { -> async arrow (await inside)
for f, pat in [
 ('src/lib/components/channel/MessageInput.svelte', 'inputFiles.forEach((file: any) {'),
 ('src/lib/components/chat/MessageInput.svelte', 'inputFiles.forEach((file: any) {'),
 ('src/lib/components/workspace/Models/Knowledge.svelte', 'inputFiles.forEach((file: any) {'),
 ('src/lib/components/workspace/common/MemberSelector.svelte', 'userIds.forEach((id: any) {'),
]:
    s = rd(f); n = s.count(pat)
    s = s.replace(pat, pat.replace('.forEach((', '.forEach(async (').replace(') {', ') => {'))
    wr(f, s); print('1:', f, n)

# 2. subscribe((filePath: any) { -> arrow
f='src/lib/components/chat/FileNav.svelte'; s=rd(f)
pat='showFileNavPath.subscribe((filePath: any) {'
n=s.count(pat); s=s.replace(pat,'showFileNavPath.subscribe((filePath: any) => {')
wr(f,s); print('2:',f,n)

# 3. generateCompletion: (text: any)  => { -> async
f='src/lib/components/common/RichTextInput.svelte'; s=rd(f)
pat='generateCompletion: (text: any)  => {'
n=s.count(pat); s=s.replace(pat,'generateCompletion: async (text: any) => {')
wr(f,s); print('3:',f,n)

# 4. new Promise((resolve: any, reject: any) { -> arrow
f='src/lib/components/notes/NoteEditor.svelte'; s=rd(f)
pat='new Promise((resolve: any, reject: any) {'
n=s.count(pat); s=s.replace(pat,'new Promise((resolve: any, reject: any) => {')
wr(f,s); print('4:',f,n)

# 5. KnowledgeBase traverse lost name+async
f='src/lib/components/workspace/Knowledge/KnowledgeBase.svelte'; s=rd(f)
pat="const collected: DirectoryFileEntry[] = [];\n\n\t\t\t\t(handle: FileSystemDirectoryHandle, dirPath: any = '') {"
if pat not in s:
    # try with spaces
    pat=re.sub(r'\s+','\\\\s+',pat) if False else None
idx = s.find("(handle: FileSystemDirectoryHandle, dirPath: any = '') {")
print('5 idx:', idx)
if idx != -1:
    s = s[:idx] + "const traverse = async (handle: FileSystemDirectoryHandle, dirPath: string = '') {" + s[idx+len("(handle: FileSystemDirectoryHandle, dirPath: any = '') {"):]
    wr(f,s); print('5 done')

# 6. map((id: any) { -> async arrow
f='src/lib/components/workspace/common/AccessControl.svelte'; s=rd(f)
pat='pendingIds.map((id: any) {'
n=s.count(pat); s=s.replace(pat,'pendingIds.map(async (id: any) => {')
wr(f,s); print('6:',f,n)

# 7. addEventListener callback await -> async
for f in ['src/routes/(app)/workspace/prompts/create/+page.svelte','src/routes/(app)/workspace/tools/create/+page.svelte']:
    s=rd(f); pat="window.addEventListener('message', (event: any) {"
    n=s.count(pat); s=s.replace(pat,"window.addEventListener('message', async (event: any) => {")
    wr(f,s); print('7:',f,n)
