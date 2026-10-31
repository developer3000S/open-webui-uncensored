// i18next-cli.config.mjs
// Config for i18next-cli (replacement for the deprecated i18next-parser).
import { readFileSync } from 'node:fs';
import sveltePlugin from 'i18next-cli-plugin-svelte';

const getLangCodes = () => {
	const languages = JSON.parse(
		readFileSync(new URL('./src/lib/i18n/locales/languages.json', import.meta.url), 'utf-8')
	);
	return languages.map((l) => l.code);
};

export default {
	locales: getLangCodes(),
	extract: {
		input: ['src/**/*.svelte', 'src/**/*.js'],
		output: 'src/lib/i18n/locales/{{language}}/{{namespace}}.json',
		primaryLanguage: 'en',
		keySeparator: false,
		namespaceSeparator: false,
		defaultNS: 'translation',
		contextSeparator: '_',
		sort: true,
		removeUnusedKeys: false,
		// Файл содержит невалидный синтаксис Svelte ({:else} без {:if}),
		// парсер его не обрабатывает — исключаем из извлечения.
		ignore: ['src/routes/(app)/coder/**']
	},
	plugins: [new sveltePlugin()]
};
