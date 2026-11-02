import eslint from '@eslint/js';
import tseslint from '@typescript-eslint/eslint-plugin';
import tsParser from '@typescript-eslint/parser';
import svelte from 'eslint-plugin-svelte';
import globals from 'globals';

const svelteParser = svelte.parser;

// Shared language options for plain JS/TS sources. The old config used the
// deprecated eslintrc-style flags (`browser`, `es2021`, `node`) inside
// `languageOptions.globals`, which ESLint 9 flat config ignores — that is why
// every browser/node global (window, document, fetch, setTimeout, require,
// module, __dirname, ...) was reported as "not defined".
const sharedGlobals = {
  ...globals.browser,
  ...globals.node,
  ...globals.worker,
  ...globals.es2021,
  APP_VERSION: 'readonly',
  APP_BUILD_HASH: 'readonly',
  __SVELTEKIT_ADAPTER_NAME__: 'readonly',
  __SVELTEKIT_APP_VERSION_FILE__: 'readonly',
  __SVELTEKIT_APP_VERSION_POLL_INTERVAL__: 'readonly',
  __SVELTEKIT_BROWSER__: 'readonly',
  __SVELTEKIT_BUILD_DIR__: 'readonly',
  __SVELTEKIT_DEV__: 'readonly',
  __SVELTEKIT_EMBEDDED__: 'readonly',
  __SVELTEKIT_MANIFEST_APP_DIR__: 'readonly',
  __SVELTEKIT_MANIFEST_ASSETS__: 'readonly',
  __SVELTEKIT_MANIFEST_BASE_PATH__: 'readonly',
  __SVELTEKIT_MANIFEST_IMMUTABLE__: 'readonly',
  __SVELTEKIT_MANIFEST_PRERENDERED__: 'readonly',
  __SVELTEKIT_MANIFEST_ROUTES__: 'readonly',
  __SVELTEKIT_MANIFEST_SERVER__: 'readonly',
  __SVELTEKIT_MANIFEST_TYPES__: 'readonly',
  __SVELTEKIT_APP_VERSION__: 'readonly',
  __non_webpack_require__: 'readonly',
  __VITE_IS_MODERN__: 'readonly',
};

const baseConfig = {
  files: ['**/*.js', '**/*.jsx', '**/*.ts', '**/*.tsx'],
  plugins: {
    '@typescript-eslint': tseslint,
  },
  languageOptions: {
    parser: tsParser,
    ecmaVersion: 'latest',
    sourceType: 'module',
    globals: sharedGlobals,
  },
  rules: {
    ...eslint.configs.recommended.rules,
    '@typescript-eslint/no-unused-vars': [
      'warn',
      { argsIgnorePattern: '^_', varsIgnorePattern: '^_', caughtErrors: 'none' },
    ],
    '@typescript-eslint/no-explicit-any': 'off',
    // Allow optional catch binding and intentionally empty blocks such as
    // `catch {}` / `catch (_) {}` used throughout the codebase.
    'no-empty': ['error', { allowEmptyCatch: true }],
  },
};

// Node CommonJS scripts (require/module/__dirname are valid there). These
// directories have no package.json with "type", so they run as CommonJS.
const cjsConfig = {
  files: [
    'studio/scripts/**/*.js',
    'studio/app/tools/**/scripts/**/*.js',
    'studio/app/tools/**/vite.config.js',
  ],
  languageOptions: {
    sourceType: 'commonjs',
    globals: sharedGlobals,
  },
};

// The repository root is an ES module ("type": "module" in package.json), so
// top-level CommonJS scripts must declare themselves explicitly.
const batchCjsOverride = {
  files: ['batch.js'],
  languageOptions: {
    sourceType: 'commonjs',
    globals: sharedGlobals,
  },
};

// Generated build artifacts and third-party code must not be linted.
const ignoreConfig = {
  ignores: [
    '**/node_modules/**',
    '**/node_modules_linux/**',
    '.svelte-kit/**',
    'build/**',
    'dist/**',
    'studio/app/dist/**',
    'studio/app/frontend/dist/**',
    'backend/open_webui/static/**',
    'backend/data/**',
    'static/pyodide/**',
    'static/sql.js/**',
    'openwebui_offline_packages/**',
    'test/**',
    '**/*-venv/**',
    '**/site-packages/**',
  ],
};

// React JSX sources must be parsed with the TypeScript parser configured for
// JSX. Without `jsx: true` every `.jsx` file failed with
// "Parsing error: Unexpected token <".
const jsxConfig = {
  files: ['**/*.jsx'],
  languageOptions: {
    parser: tsParser,
    parserOptions: {
      ecmaVersion: 'latest',
      sourceType: 'module',
      jsx: true,
    },
    globals: sharedGlobals,
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
    globals: sharedGlobals,
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
  ignoreConfig,
  baseConfig,
  cjsConfig,
  batchCjsOverride,
  jsxConfig,
  svelteConfig,
];