import re, pathlib

# Function params with defaults: ident: type = default  -> must become arrow if function expression lost =>
param_default = re.compile(r"\(\s*([A-Za-z_$][\w$]*)\s*:\s*[^()]*?\s*=\s*(?:''|\"\"|`|true|false|null|undefined|\{\}|\[\]|\d+|[A-Za-z_$][\w$.]*)\s*\)\s*\{")
callback_named = re.compile(r"(onChange|onTaskClick|regenerateResponse|onUpdate)=\{\(([^{}]*?)\)\s*\{")
event_attr = re.compile(r"(on:(?:click|change|input|submit|keyup|keydown|focus|blur|paste|wheel|mousedown|mouseup))=\{\(([^{}]*?)\)\s*\{")

def has_default(inner):
    # split params at top level commas; check any param has '=' after ':' 
    return bool(re.search(r":[^,=]+=", inner)) or ('=' in inner)

files=0; fixes=0
for p in pathlib.Path('src').rglob('*'):
    if p.suffix not in ('.ts','.svelte'): continue
    txt=p.read_text(encoding='utf-8',errors='ignore')
    orig=txt
    cnt=[0]
    def r1(m):
        head = txt[:m.start()]
        # ensure preceded by '=' or '.' (i.e., .then( / = (..) { ) but NOT '=>' already there and not a plain call with args
        prev = head[-1] if head else ''
        # only convert when it looks like an assignment/callback: preceded by '=' (e.g. onChange={( ... ) {) handled elsewhere
        return m.group(0)
    # Pattern A: X={(params) {   where params look like a single typed param list (contains ':' or is short ident) and no '=>' inside braces start
    patA = re.compile(r"=\{\(([^{}\n]{0,120}?)\)\s*\{")
    def repA(m):
        inner=m.group(1)
        seg = txt[m.end():m.end()+40]
        if '=>' in inner: return m.group(0)
        # treat as callback if inner looks like params: ident(:type)?(, ident(:type)?)*
        if re.fullmatch(r"\s*[A-Za-z_$][\w$]*(\s*:\s*[^,]+)?(\s*,\s*[A-Za-z_$][\w$]*(\s*:\s*[^,]+)?)?\s*", inner):
            cnt[0]+=1
            return "={(" + inner + ") => {"
        return m.group(0)
    txt = patA.sub(repA, txt)
    # Pattern B: on:evt={(params) {
    def repB(m):
        inner=m.group(2)
        if '=>' in inner: return m.group(0)
        if re.fullmatch(r"\s*[A-Za-z_$][\w$]*(\s*:\s*.+?)?\s*", inner):
            cnt[0]+=1
            return m.group(1)+"={(" + inner + ") => {"
        return m.group(0)
    txt = event_attr.sub(repB, txt)
    # Pattern C: name(params: type = default) {  -- function decl missing arrow after '=' e.g. const f = (x: any = '') {
    patC = re.compile(r"((?:const|let|var)\s+[A-Za-z_$][\w$]*\s*=\s*)\(([^()\n]{1,160}?)\)\s*\{")
    def repC(m):
        inner=m.group(2)
        if '=>' in inner: return m.group(0)
        if re.search(r":[^,)]]*=", inner) or re.fullmatch(r"\s*[A-Za-z_$][\w$]*(\s*:\s*[^,]+)?(\s*,\s*[A-Za-z_$][\w$]*(\s*:\s*[^,]+)?)*\s*", inner):
            # require it to look like params (has : or multiple idents), skip plain calls like if(...)
            if ':' in inner or ',' in inner:
                cnt[0]+=1
                return m.group(1)+"(" + inner + ") => {"
        return m.group(0)
    txt = patC.sub(repC, txt)
    if txt!=orig:
        p.write_text(txt,encoding='utf-8'); files+=1; fixes+=cnt[0]
print(f"FILES={files} FIXES={fixes}")
