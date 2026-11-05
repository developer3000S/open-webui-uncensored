import adapter from '@sveltejs/adapter-static';
import { sveltekit } from '@sveltejs/kit/vite';
import * as child_process from 'node:child_process';
import fs from 'node:fs';
import { vitePreprocess } from '@sveltejs/vite-plugin-svelte';
import { defineConfig } from 'vite';

import { viteStaticCopy } from 'vite-plugin-static-copy';

// Known-benign upstream Svelte compiler warnings that do not break the build
// and come from the open-webui upstream sources.
const IGNORED_SWELTE_CODES = new Set([
  'missing-exports-condition', // Ignore svelte field without exports condition

  'export_let_unused',
  'element_invalid_self_closing_tag',
  'a11y_consider_explicit_label',
  'a11y_no_noninteractive_element_interactions',
  'a11y_no_static_element_interactions',
  'a11y_missing_attribute',
  'css_unused_selector',
  'reactive_declaration_module_script_dependency',
  'a11y_interactive_supports_focus',
  'a11y_click_events_have_key_events',
  'state_referenced_locally',
]);

export default defineConfig({
  // SvelteKit 3 removed the built-in `$lib` alias; restore it so the existing
  // sources (which import from `$lib/...`) keep working without a rewrite.
  resolve: {
    alias: {
      $lib: new URL('./src/lib', import.meta.url).pathname
    }
  },
  // Отключаем статический анализ, чтобы обойти проблему с parseSync
  optimizeDeps: {
    exclude: ['@sveltejs/kit']
  },
  plugins: [
    sveltekit({
      // Consult https://kit.svelte.dev/docs/integrations#preprocessors
      // for more information about preprocessors
      preprocess: vitePreprocess(),

      // SvelteKit options (previously in the `kit` namespace of svelte.config.js)
      adapter: adapter({
        pages: 'build',
        assets: 'build',
        fallback: 'index.html'
      }),
      // poll for new version name every 60 seconds (to trigger reload mechanic in +layout.svelte)
      version: {
        name: (() => {
          try {
            return child_process.execSync('git rev-parse HEAD').toString().trim();
          } catch {
            // if git is not available, fallback to package.json version
            // or current timestamp
            try {
              return (
                JSON.parse(fs.readFileSync(new URL('./package.json', import.meta.url), 'utf8'))
                  ?.version || Date.now().toString()
              );
            } catch {
              return Date.now().toString();
            }
          }
        })(),
        pollInterval: 60000
      },
      onwarn: (warning, defaultHandler) => {
        if (warning.code && IGNORED_SWELTE_CODES.has(warning.code)) {
          return;
        }
        defaultHandler(warning);
      }
    }),
    viteStaticCopy({
      targets: [
        {
          src: 'node_modules/onnxruntime-web/dist/*.jsep.*',
          dest: 'wasm'
        }
      ]
    })
  ],
  define: {
    APP_VERSION: JSON.stringify(process.env.npm_package_version),
    APP_BUILD_HASH: JSON.stringify(process.env.APP_BUILD_HASH || 'dev-build')
  },
  build: {
    sourcemap: true,
    // lightningcss emits "Unknown at rule: @apply" / ":global" warnings for
    // Tailwind-style directives in .svelte <style> blocks. Switch to esbuild
    // to silence those warnings; the build result is unaffected.
    cssMinify: 'esbuild'
  },
  worker: {
    format: 'es'
  },
  esbuild: {
    supported: {
      'svelte:preprocess': true
    }
  }
});
