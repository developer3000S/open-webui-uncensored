// See https://kit.svelte.dev/docs/types#app
// for information about these interfaces
declare const APP_VERSION: string;
declare const APP_BUILD_HASH: string;

declare var gapi: any;
declare var google: any;

declare global {
	namespace App {
		// interface Error {}
		// interface Locals {}
		// interface PageData {}
		// interface Platform {}
	}

	var APP_VERSION: string;
	var APP_BUILD_HASH: string;
}

export {};
