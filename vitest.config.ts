import { defineConfig } from 'vitest/config';
import { svelte } from '@sveltejs/vite-plugin-svelte';
import path from 'path';
import { fileURLToPath } from 'url';
import sveltePreprocess from 'svelte-preprocess';

const __dirname = path.dirname(fileURLToPath(import.meta.url));

export default defineConfig({
  plugins: [
    svelte({
      preprocess: sveltePreprocess(),
    }),
  ],
  resolve: {
    alias: {
      '$lib': path.resolve(__dirname, '../src/lib'),
    },
  },
  test: {
    globals: true,
    environment: 'jsdom',
    setupFiles: ['./vitest.setup.ts'],
    include: ['**/*.{test,spec}.{js,ts,svelte}', '**/test-*.{js,ts}'],
  },
});