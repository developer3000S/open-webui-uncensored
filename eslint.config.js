import eslint from '@eslint/js';
import tseslint from '@typescript-eslint/eslint-plugin';
import parser from '@typescript-eslint/parser';
import svelte from 'eslint-plugin-svelte';

const svelteParser = svelte.parser;

const baseConfig = {
  files: ['**/*.js', '**/*.jsx', '**/*.ts', '**/*.tsx'],
  plugins: {
    '@typescript-eslint': tseslint,
  },
  languageOptions: {
    globals: {
      browser: true,
      es2021: true,
      node: true,
      process: 'readonly',
      URL: 'readonly',
      Buffer: 'readonly',
      console: 'readonly',
    },
    parserOptions: {
      ecmaVersion: 'latest',
      sourceType: 'module',
    },
  },
  rules: {
    ...eslint.configs.recommended.rules,
    '@typescript-eslint/no-unused-vars': ['warn', { argsIgnorePattern: '^_' }],
    '@typescript-eslint/no-explicit-any': 'off',
  },
};

const svelteConfig = {
  files: ['**/*.svelte'],
  plugins: {
    svelte,
  },
  languageOptions: {
    parser: svelteParser,
    parserOptions: {
      parser: '@typescript-eslint/parser',
      ecmaVersion: 'latest',
      sourceType: 'module',
    },
  },
  settings: {
    svelte: {
      compilerOptions: {
        dev: true,
      },
    },
  },
  rules: {
    'svelte/valid-compile': 'error',
  },
};

export default [
  baseConfig,
  svelteConfig,
];