import fs from 'node:fs';
import path from 'node:path';

const root = process.cwd();
const buildDir = path.join(root, 'build');

const failures = [];
const warnings = [];

const stat = (file) => {
	try {
		return fs.statSync(path.join(root, file));
	} catch {
		return null;
	}
};

const index = stat('build/index.html');
if (!index) {
	failures.push('build/index.html отсутствует — фронтенд не собран');
} else if (index.size < 1024) {
	failures.push(`build/index.html подозрительно мал (${index.size} байт)`);
}

const appDir = stat('build/_app/immutable');
if (!appDir || !appDir.isDirectory()) {
	failures.push('build/_app/immutable отсутствует — SvelteKit-бандл не создан');
}

// loader.js и custom.css в upstream намеренно пустые (точки кастомизации),
// поэтому проверяем только их наличие, а не размер.
for (const file of ['build/static/loader.js', 'build/static/custom.css']) {
	if (!stat(file)) warnings.push(`${file} отсутствует`);
}

for (const warning of warnings) console.warn(`WARN: ${warning}`);
for (const failure of failures) console.error(`ERROR: ${failure}`);

if (failures.length > 0) {
	process.exit(1);
}

console.log('OK: build/index.html и build/_app/immutable на месте');
