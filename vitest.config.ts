import { defineConfig } from 'vitest/config';

export default defineConfig({
	define: {
		APP_VERSION: JSON.stringify(process.env.npm_package_version || 'test-version'),
		APP_BUILD_HASH: JSON.stringify(process.env.APP_BUILD_HASH || 'test-build-hash')
	},
	// SvelteKit 3 removed the `$lib` alias; keep it working for tests too.
	resolve: {
		alias: {
			$lib: new URL('./src/lib', import.meta.url).pathname
		}
	},
	test: {
		globals: true,
		environment: 'jsdom',
		include: ['src/**/*.{test,spec}.{js,ts}'],
	}
});
