import { sveltekit } from '@sveltejs/kit/vite';
import { defineConfig } from 'vite';
import { svelte } from '@sveltejs/vite-plugin-svelte';

import { viteStaticCopy } from 'vite-plugin-static-copy';

export default defineConfig({
  plugins: [
    svelte({
      onwarn: (warning, handler) => {
        if (warning.code === 'svelte-ignore-export-condition' || warning.code === 'css-unused-selector') {
          return;
        }
        handler(warning);
      }
    }),
    sveltekit(),
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