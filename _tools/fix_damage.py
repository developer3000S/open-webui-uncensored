#!/usr/bin/env python3
import re, os

ROOT = "/workspace/src"

BOGUS = [
    (re.compile(r"(\b(?:if|while)\s*\()([A-Za-z_$][\w$]*)\s*:\s*any\b"), r"\1\2"),
    (re.compile(r"(\belse\s+if\s*\()([A-Za-z_$][\w$]*)\s*:\s*any\b"), r"\1\2"),
    (re.compile(r"([A-Za-z_$][\w$]*)\s*:\s*any\s*(===|!==|==|!=)"), r"\1 \2"),
]

NOCOMMA = re.compile(r"([A-Za-z_$][\w$]*)\s*:\s*(any|string|number|boolean)(?=\s+[A-Za-z_$][\w$]*(?:\s*[:=)]))")

def fix_line(line):
    for _ in range(4):
        prev = line
        for pat, rep in BOGUS:
            line = pat.sub(rep, line)
        if prev == line:
            break
    for _ in range(8):
        prev = line
        line = NOCOMMA.sub(r"\1: \2,", line)
        if prev == line:
            break
    return line

changed = 0
for dirpath, _, files in os.walk(ROOT):
    for fn in files:
        if not (fn.endswith(".svelte") or fn.endswith(".ts")):
            continue
        p = os.path.join(dirpath, fn)
        try:
            src = open(p, encoding="utf-8").read()
        except Exception:
            continue
        lines = src.split("\n")
        out = [fix_line(ln) for ln in lines]
        if out != lines:
            open(p, "w", encoding="utf-8").write("\n".join(out))
            changed += 1
print("files changed:", changed)
