import { setGlobalDispatcher, ProxyAgent } from 'undici';
import { mkdir, writeFile, readFile, stat, cp, access } from 'fs/promises';
import path from 'path';

// Pyodide runs entirely in the browser (see src/lib/workers/pyodide.worker.ts),
// so this build script only has to *stage* the Pyodide distribution and any extra
// wheels into static/pyodide/. It must never boot the WASM interpreter on Node:
// that requires downloading the full runtime and fails inside sandboxed/Docker builds.
async function downloadPackages() {
console.log('Preparing Pyodide packages (browser runtime staging only)');

const srcDir = 'node_modules/pyodide';
let hasSrc = false;
try {
hasSrc = (await stat(srcDir)).isDirectory();
} catch {
hasSrc = false;
}

if (!hasSrc) {
console.warn(`Pyodide package not found at ${srcDir}, nothing to prepare`);
return;
}

// Sanity check: the lock file shipped with the npm package is required by
// downloadPyPIWheels(), which registers the extra pure-Python wheels in it.
try {
await access(path.join(srcDir, 'pyodide-lock.json'));
} catch {
console.warn('pyodide-lock.json missing in node_modules/pyodide; wheel registration will be skipped');
}

console.log('Pyodide distribution found; no server-side interpreter boot required');
}

/**
 * Copy the pyodide npm package into static/pyodide so Vite serves it to the browser.
 */
async function copyPyodide() {
console.log('Copying Pyodide files into static directory');
const srcDir = 'node_modules/pyodide';
const destDir = 'static/pyodide';

let hasSrc = false;
try {
hasSrc = (await stat(srcDir)).isDirectory();
} catch {
hasSrc = false;
}
if (!hasSrc) {
console.warn(`${srcDir} not found, skipping copy`);
return;
}

let alreadyCopied = false;
try {
const destStat = await stat(destDir);
if (destStat.isDirectory()) {
alreadyCopied = true;
}
} catch {
alreadyCopied = false;
}

if (alreadyCopied) {
console.log('Directory static/pyodide already exists, skipping copy');
return;
}

await mkdir(destDir, { recursive: true });
await cp(srcDir, destDir, { recursive: true, force: true });
console.log('Copied node_modules/pyodide -> static/pyodide');
}

/**
 * Download pure-Python wheels from PyPI and save them into static/pyodide/.
 */
async function downloadPyPIWheels() {
const lockPath = 'static/pyodide/pyodide-lock.json';
let lockData;
try {
lockData = JSON.parse(await readFile(lockPath, 'utf-8'));
} catch {
console.warn('Could not read pyodide-lock.json, skipping PyPI wheel download');
return;
}

const pypiPackages = ['numpy', 'pandas', 'scipy', 'matplotlib', 'scikit-learn', 'tensorflow', 'pytorch', 'requests', 'flask', 'django', 'fastapi', 'uvicorn', 'pillow', 'opencv-python', 'tqdm', 'jupyter', 'pydantic', 'sqlalchemy', 'boto3', 'psycopg2-binary', 'mysqlclient', 'redis', 'requests-toolbelt', 'aiohttp', 'httpx'];

for (const pkg of pypiPackages) {
console.log(`Fetching PyPI metadata for: ${pkg}`);
const res = await fetch(`https://pypi.org/pypi/${pkg}/json`);
if (!res.ok) {
console.error(`Failed to fetch PyPI metadata for ${pkg}: ${res.status}`);
continue;
}
const meta = await res.json();
const version = meta.info.version;
const files = meta.urls || [];
const wheel = files.find(f => f.filename.endsWith('.whl') && f.filename.includes('py3-none-any'));
if (!wheel) {
console.warn(`No pure-Python wheel found for ${pkg}==${version}, skipping`);
continue;
}
const dest = `static/pyodide/${wheel.filename}`;
try {
await access(dest);
console.log(`  Already exists: ${wheel.filename}`);
} catch {
console.log(`  Downloading: ${wheel.filename}`);
const wheelRes = await fetch(wheel.url);
if (!wheelRes.ok) {
console.error(`  Failed to download ${wheel.filename}: ${wheelRes.status}`);
continue;
}
const buffer = Buffer.from(await wheelRes.arrayBuffer());
await writeFile(dest, buffer);
console.log(`  Saved: ${dest} (${buffer.length} bytes)`);
}

const normalizedName = pkg.replace(/-/g, '_');
if (!lockData.packages[normalizedName]) {
lockData.packages[normalizedName] = {
name: normalizedName,
version: version,
file_name: wheel.filename,
install_dir: 'site',
sha256: wheel.digests?.sha256 || '',
package_type: 'package',
imports: [normalizedName],
depends: []
};
console.log(`  Added ${normalizedName}==${version} to pyodide-lock.json`);
}
}

await writeFile(lockPath, JSON.stringify(lockData, null, 2));
console.log('Updated pyodide-lock.json with PyPI packages');
}

function initNetworkProxyFromEnv() {
const proxyConfig = process.env.HTTP_PROXY || process.env.http_proxy;
const httpsProxyConfig = process.env.HTTPS_PROXY || process.env.https_proxy;

if (proxyConfig) {
const proxyUrl = new URL(proxyConfig);
setGlobalDispatcher(new ProxyAgent(proxyUrl.href));
} else if (httpsProxyConfig) {
const proxyUrl = new URL(httpsProxyConfig);
setGlobalDispatcher(new ProxyAgent(proxyUrl.href));
}
}

initNetworkProxyFromEnv();
await downloadPackages();
await copyPyodide();
await downloadPyPIWheels();
