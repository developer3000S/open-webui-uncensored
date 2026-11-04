import re

f = 'src/lib/components/workspace/Knowledge/KnowledgeBase.svelte'
s = open(f).read()

# locate the arrow-function traverse (possibly already head-patched or not)
m = re.search(r'const traverse = async \(handle: FileSystemDirectoryHandle, dirPath: string = \'\'\)\s*=>\s*\{', s)
if m:
    start = m.start()
    # brace-match body
    i = m.end() - 1  # at '{'
    depth = 0
    j = i
    while j < len(s):
        if s[j] == '{':
            depth += 1
        elif s[j] == '}':
            depth -= 1
            if depth == 0:
                break
        j += 1
    # after closing '}' expect ';' (maybe with whitespace)
    k = j + 1
    while k < len(s) and s[k] in ' \t':
        k += 1
    if k < len(s) and s[k] == ';':
        body = s[i+1:j]
        replacement = "async function traverse(handle: FileSystemDirectoryHandle, dirPath = '') {" + body + "}"
        s = s[:start] + replacement + s[k+1:]
        open(f, 'w').write(s)
        print("KB restored to function declaration")
    else:
        print("KB no semicolon found at", k, repr(s[k:k+5]))
else:
    print("KB pattern MISS (maybe already fixed)")
