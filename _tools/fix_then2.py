import re, pathlib
pat = re.compile(r"\.then\(\s*\(([^()]*?)\)\s*\{")
single = re.compile(r"^\s*[A-Za-z_$][\w$]*(\s*:\s*.+?)?\s*$")
files = 0; fixes = 0
for p in pathlib.Path('src').rglob('*'):
    if p.suffix not in ('.ts', '.svelte', '.js'):
        continue
    txt = p.read_text(encoding='utf-8', errors='ignore')
    def rep(m):
        global_fixes[0] += 1
        inner = m.group(1)
        if single.match(inner):
            return ".then((" + inner.strip() + ") => {"
        return m.group(0)
    global_fixes = [0]
    new, n = pat.subn(rep, txt)
    if new != txt:
        p.write_text(new, encoding='utf-8')
        files += 1; fixes += global_fixes[0]
print(f"FILES_TOUCHED={files} FIXES={fixes}")
# remaining check
rem = 0
for p in pathlib.Path('src').rglob('*'):
    if p.suffix in ('.ts', '.svelte', '.js'):
        t = p.read_text(encoding='utf-8', errors='ignore')
        for m in pat.finditer(t):
            if single.match(m.group(1)):
                rem += 1
print("REMAINING=", rem)
