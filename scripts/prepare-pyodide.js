import { loadPyodide } from 'pyodide';
import { setGlobalDispatcher, ProxyAgent } from 'undici';
import { writeFile, readFile, copyFile, readdir, rmdir, access } from 'fs/promises';
import path from 'path';

let pyodide;

async function copyDir(src, dest) {
    const entries = await readdir(src, { withFileTypes: true });
    await writeFile(dest, '', { flag: 'wx' });

    for (const entry of entries) {
        const srcPath = path.join(src, entry.name);
        const destPath = path.join(dest, entry.name);

        if (entry.isDirectory()) {
            await copyDir(srcPath, destPath);
        } else {
            await copyFile(srcPath, destPath);
        }
    }
}

async function copyPyodide() {
    console.log('Copying Pyodide files into static directory');
    const srcDir = 'node_modules/pyodide';
    const destDir = 'static/pyodide';

    try {
        await access(destDir);
        console.log('Directory static/pyodide already exists, skipping copy');
        return;
    } catch (err) {
        if (err.code !== 'ENOENT') {
            throw err; // Перебрасываем ошибку, если это не ошибка отсутствия директории
        }
        await writeFile(destDir, '', { flag: 'wx' });
    }

    await copyDir(srcDir, destDir);
}

async function downloadPackages() {
    console.log('Preparing Pyodide packages');
    try {
        const localPyodidePath = path.join(process.cwd(), 'node_modules', 'pyodide');
        pyodide = await loadPyodide({
            indexURL: localPyodidePath
        });
        console.log('Using local Pyodide from node_modules');
    } catch (err) {
        console.log('Local Pyodide not found, attempting to load from CDN');
        try {
            pyodide = await loadPyodide({
                indexURL: 'https://cdn.jsdelivr.net/pyodide/v0.23.4/full/'
            });
            console.log('Loaded Pyodide from CDN');
        } catch (cdnErr) {
            console.error('Failed to load Pyodide from CDN:', cdnErr);
            throw new Error('Failed to load Pyodide. Make sure you have an internet connection or local Pyodide files.');
        }
    }

    // Загружаем micropip как пакет
    await pyodide.loadPackage('micropip');
    
    // Устанавливаем numpy через micropip
    await pyodide.runPythonAsync(`
        import micropip
        await micropip.install('numpy')
    `);

    console.log('Micropip installed and numpy added successfully');
    // Не сохраняем состояние micropip, так как оно не требуется для работы
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
    const noProxyConfig = process.env.NO_PROXY || process.env.no_proxy;

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