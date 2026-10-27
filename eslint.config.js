// Flat config for ESLint 9 (migrated from .eslintrc.cjs).
// In ESLint >= 9 the .eslintrc.* format is no longer used; ignore patterns
// live in `ignores` below instead of .eslintignore.
import js from '@eslint/js';
import globals from 'globals';
import tseslint from 'typescript-eslint';
import svelte from 'eslint-plugin-svelte';
import cypress from 'eslint-plugin-cypress/flat';
import prettier from 'eslint-config-prettier';

export default tseslint.config(
	{
		// Replaces .eslintignore
		ignores: [
			'.DS_Store',
			'node_modules',
			'build',
			'.svelte-kit',
			'package',
			'static/**',
			'dist/**',
			'backend/**',
			'.env',
			'.env.*',
			'!.env.example',
			// Lockfiles are not lint sources
			'pnpm-lock.yaml',
			'package-lock.json',
			'yarn.lock',
			// Generated i18n bundles
			'src/lib/i18n/locales/**',
			// Test fixtures and legacy studio folder
			'test/**',
			'studio/**'
		]
	},
	js.configs.recommended,
	...tseslint.configs.recommended,
	...svelte.configs['flat/recommended'],
	cypress.configs.recommended,
	{
		languageOptions: {
			globals: {
				...globals.browser,
				...globals.node
			}
		}
	},
	{
		files: ['**/*.svelte'],
		languageOptions: {
			parserOptions: {
				parser: tseslint.parser
			}
		}
	},
	{
		rules: {
			// The codebase relies on dynamic typing in many places; keep these
			// as warnings so new violations are visible without breaking CI.
			'@typescript-eslint/no-explicit-any': 'off',
			'@typescript-eslint/no-unused-vars': [
				'warn',
				{ argsIgnorePattern: '^_', varsIgnorePattern: '^_' }
			],
			'svelte/no-navigation-without-resolve': 'off',
			'svelte/valid-compile': 'off'
		}
	},
	// Must be last: turns off all stylistic rules that conflict with Prettier.
	prettier
);
