// i18next-cli.config.mjs
// Config for i18next-cli (replacement for the deprecated i18next-parser).
import { readFileSync } from 'node:fs';

const getLangCodes = () => {
	const languages = JSON.parse(
		readFileSync(new URL('./src/lib/i18n/locales/languages.json', import.meta.url), 'utf-8')
	);
	return languages.map((l) => l.code);
};

export default {
	parserOptions: {
		contextSeparator: '_',
		keySeparator: false,
		namespaceSeparator: false,
		defaultNamespace: 'translation',
		keepRemoved: false,
		sort: true,
		lexers: {
			svelte: ['html'],
			js: ['default'],
			ts: ['default'],
			default: ['default']
		}
	},
	input: ['src/**/*.js', 'src/**/*.svelte'],
	output: 'src/lib/i18n/locales/$LOCALE/$NAMESPACE.json',
	locales: getLangCodes(),
	createOldCatalogs: false,
	verbose: true
};
