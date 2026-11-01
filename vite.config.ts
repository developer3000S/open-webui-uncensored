import adapter from '@sveltejs/adapter-static';
import { sveltekit } from '@sveltejs/kit/vite';
import * as child_process from 'node:child_process';
import fs from 'node:fs';
import { vitePreprocess } from '@sveltejs/vite-plugin-svelte';
import { defineConfig } from 'vite';

import { viteStaticCopy } from 'vite-plugin-static-copy';

export default defineConfig({
  // SvelteKit 3 removed the built-in `$lib` alias; restore it so the existing
  // sources (which import from `$lib/...`) keep working without a rewrite.
  resolve: {
    alias: {
      $lib: new URL('./src/lib', import.meta.url).pathname
    }
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

      // remaining options are passed through to vite-plugin-svelte
      onwarn: (warning, handler) => {
        const { code } = warning;
        if (code === 'css-unused-selector' || code === 'svelte-ignore-export-condition') return;

        handler(warning);
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
    sourcemap: true
  },
  worker: {
    format: 'es'
  },
  esbuild: {
    pure: process.env.ENV === 'dev' ? [] : ['console.log', 'console.debug', 'console.error']
  }
});
