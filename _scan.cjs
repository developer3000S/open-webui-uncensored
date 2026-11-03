const fs = require('fs');
const path = require('path');
const { parse } = require('svelte/compiler');

function walk(dir, out=[]) {
  for (const e of fs.readdirSync(dir, {withFileTypes:true})) {
    const p = path.join(dir, e.name);
    if (e.isDirectory()) { if (e.name !== 'node_modules' && e.name !== '.svelte-kit' && e.name !== '.git') walk(p, out); }
    else if (e.name.endsWith('.svelte')) out.push(p);
  }
  return out;
}
const files = walk('src');
let bad = [];
for (const f of files) {
  const src = fs.readFileSync(f, 'utf8');
  try { parse(src, {modern: true}); } catch (err) {
    let msg = err.message || String(err);
    if (err instanceof Array) msg = err.map(e=>e.message).join('; ');
    bad.push({f, msg, start: err.start ? err.start.line : ''});
  }
}
console.log('TOTAL_SVELTE:', files.length);
console.log('PARSE_FAIL:', bad.length);
for (const b of bad) console.log(b.f + ':' + b.start + ' | ' + b.msg.replace(/\n/g,' ').slice(0,120));
