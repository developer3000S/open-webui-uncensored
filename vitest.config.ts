import { defineConfig } from 'vitest/config';

export default defineConfig({
	define: {
		APP_VERSION: JSON.stringify(process.env.npm_package_version || 'test-version'),
		APP_BUILD_HASH: JSON.stringify(process.env.APP_BUILD_HASH || 'test-build-hash')
	},
	test: {
		globals: true,
		environment: 'jsdom',
		include: ['src/**/*.{test,spec}.{js,ts}'],
	}
});
