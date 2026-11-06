import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));

// Function to patch package.json exports
function patchExports(pkgPath) {
  try {
    const pkgJson = JSON.parse(fs.readFileSync(pkgPath, 'utf8'));
    if (pkgJson.exports && pkgJson.exports['.']) {
      const exportsDot = pkgJson.exports['.'];
      const needsFix = !exportsDot.module || !exportsDot.import;
      
      // If missing module or import, add them pointing to svelte/default
      if (needsFix) {
        const targetFile = exportsDot.svelte || exportsDot.default || exportsDot.types || './index.js';
        if (!exportsDot.module) exportsDot.module = targetFile;
        if (!exportsDot.import) exportsDot.import = targetFile;
        fs.writeFileSync(pkgPath, JSON.stringify(pkgJson, null, 2));
        console.log(`Patched exports in ${pkgPath}`);
      }
    }
  } catch (e) {
    console.error(`Error patching ${pkgPath}:`, e.message);
  }
}

// Patch paneforge itself
patchExports(path.join(__dirname, '../node_modules/paneforge/package.json'));

// Patch paneforge's nested dependencies
const paneforgeDeps = path.join(__dirname, '../node_modules/paneforge/node_modules');
if (fs.existsSync(paneforgeDeps)) {
  fs.readdirSync(paneforgeDeps).forEach(dep => {
    const depPath = path.join(paneforgeDeps, dep, 'package.json');
    if (fs.existsSync(depPath)) {
      patchExports(depPath);
    }
  });
}

// Also patch runed specifically (since it's causing issues)
const runedPath = path.join(__dirname, '../node_modules/paneforge/node_modules/runed/package.json');
if (fs.existsSync(runedPath)) {
  patchExports(runedPath);
}