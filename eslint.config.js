import eslint from '@eslint/js';
import tseslint from '@typescript-eslint/eslint-plugin';
import tsParser from '@typescript-eslint/parser';
import sveltePlugin from 'eslint-plugin-svelte';
import globals from 'globals';

// eslint-plugin-svelte v3 exposes its flat-config presets under the `configs`
// map (`svelte.parser` does NOT exist in this major version — using it made
// every .svelte file fail with "Parsing error: Unexpected token <").
const svelteBase = sveltePlugin.configs['flat/base'];

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
  // Web/Worker standard types used as type annotations (not values) in sources.
  RequestInit: 'readonly',
  Transferable: 'readonly',
  // Google platform scripts loaded at runtime in the browser
  // (src/lib/utils/google-drive-picker.ts uses gapi/google pickers).
  gapi: 'readonly',
  google: 'readonly',
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
    // The base `no-unused-vars` (from eslint:recommended) has no ignore
    // patterns by default and double-reports TS files alongside the
    // @typescript-eslint version. Disable it; the TS rule below handles
    // both JS and TS with proper `^_` ignore patterns.
    'no-unused-vars': 'off',
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
// Node-only sources (CommonJS scripts and build tooling). These run under
// Node, so browser/worker globals would be false positives there — use the
// node + es2021 global sets only. This also fixes `no-redeclare` errors for
// files like `const crypto = require('crypto')` (the browser global `crypto`
// must not be registered for Node scripts).
const nodeGlobals = { ...globals.node, ...globals.es2021 };

// Node built-ins that share their name with a browser global (crypto, process,
// Buffer, ...). When the `globals.browser` set is also active (via the base
// config), redeclaring them with `require()` triggers false `no-redeclare`
// errors. These files legitimately shadow the browser name with the Node
// module, so disable that rule for all Node/CommonJS sources here.
const cjsRules = {
  'no-redeclare': ['error', { builtinGlobals: false }],
};

const cjsConfig = {
  files: [
    'studio/scripts/**/*.js',
    'studio/app/tools/**/scripts/**/*.js',
    // Any CJS file that uses `require`/`module.exports`, including Vite
    // configs written in CommonJS style anywhere in the repo.
    '**/vite.config.js',
  ],
  languageOptions: {
    parserOptions: {
      ecmaVersion: 'latest',
      sourceType: 'commonjs',
    },
    globals: nodeGlobals,
  },
  rules: cjsRules,
};

// The repository root is an ES module ("type": "module" in package.json), so
// top-level CommonJS scripts must declare themselves explicitly.
const batchCjsOverride = {
  files: ['batch.js'],
  languageOptions: {
    parserOptions: {
      ecmaVersion: 'latest',
      sourceType: 'commonjs',
    },
    globals: nodeGlobals,
  },
  rules: cjsRules,
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

// Use the plugin's own flat/base preset so .svelte files get the correct
// parser and preprocessor, then layer our globals/rules on top. The base
// preset must come first: later configs merge languageOptions for the same
// files.
const svelteGlobalsConfig = {
  files: ['**/*.svelte'],
  languageOptions: {
    // Parse `<script lang="ts">` blocks with the TypeScript parser; without
    // this every typed component failed with "Parsing error: Unexpected token :".
    parserOptions: {
      parser: tsParser,
      ecmaVersion: 'latest',
      sourceType: 'module',
    },
    globals: sharedGlobals,
  },
  rules: {
    // `svelte/valid-compile` requires compiler options matching vite config;
    // keep it off to avoid false positives from legacy syntax in components.
    'svelte/valid-compile': 'off',
  },
};

export default [
  ignoreConfig,
  baseConfig,
  cjsConfig,
  batchCjsOverride,
  jsxConfig,
  ...svelteBase,
  svelteGlobalsConfig,
];