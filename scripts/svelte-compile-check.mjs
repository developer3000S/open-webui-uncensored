import { compile } from 'svelte/compiler';
import fs from 'fs';
const files = process.argv.slice(2);
let fail = 0;
for (const f of files) {
  const source = fs.readFileSync(f, 'utf8');
  try {
    const { warnings } = compile(source, { filename: f, generate: 'client' });
    const a11y = warnings.filter(w => w.code && w.code.startsWith('a11y'));
    console.log(`OK ${f} (warnings: ${warnings.length}, a11y: ${a11y.length})`);
    for (const w of a11y.slice(0,5)) console.log('  a11y:', w.code, w.start?.line);
  } catch (e) {
    fail = 1;
    console.error(`FAIL ${f}: ${e.message}`);
    if (e.frame) console.error(e.frame.split('\n').slice(0,8).join('\n'));
  }
}
process.exit(fail);
