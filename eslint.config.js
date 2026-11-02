import svelte from 'eslint-plugin-svelte';
import parser from '@typescript-eslint/parser';
import svelteParser from 'svelte-eslint-parser';

const svelteParserInstance = svelteParser;

const baseConfig = {
  files: ['**/*.js', '**/*.jsx', '**/*.ts', '**/*.tsx', '**/*.svelte'],
  languageOptions: {
    globals: {
      browser: true,
      es2021: true,
    },
  },
  rules: {
    'no-console': 'warn',
    'no-unused-vars': 'warn',
    'no-undef': 'error',
  },
};

const svelteConfig = {
  files: ['**/*.svelte'],
  plugins: {
    svelte,
  },
  languageOptions: {
    parser: svelteParserInstance,
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

const jsConfig = {
  files: ['**/*.js', '**/*.jsx', '**/*.ts', '**/*.tsx'],
  languageOptions: {
    parser: parser,
    parserOptions: {
      ecmaVersion: 'latest',
      sourceType: 'module',
    },
  },
  rules: {
    '@typescript-eslint/no-unused-vars': ['warn', { argsIgnorePattern: '^_' }],
  },
};

export default [
  baseConfig,
  svelteConfig,
  jsConfig,
];