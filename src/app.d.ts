// See https://kit.svelte.dev/docs/types#app
// for information about these interfaces
declare const APP_VERSION: string;
declare const APP_BUILD_HASH: string;

declare global {
	namespace App {
		// interface Error {}
		// interface Locals {}
		// interface PageData {}
		// interface Platform {}
	}

	var APP_VERSION: string;
	var APP_BUILD_HASH: string;

	var gapi: any;
	var google: any;

	interface EventTarget {
		value?: any;
		src?: any;
		style?: any;
		scrollHeight?: any;
		files?: any;
		checked?: any;
		select?: any;
		contentWindow?: any;
		closest?: any;
		classList?: any;
	}

	interface Node {
		style?: any;
		classList?: any;
		querySelectorAll?: any;
	}

	interface Element {
		click?: any;
		style?: any;
		contentWindow?: any;
	}

	interface HTMLElement {
		value?: any;
		select?: any;
		style?: any;
		src?: any;
		videoWidth?: any;
		videoHeight?: any;
		width?: any;
		height?: any;
		muted?: any;
		currentTime?: any;
		play?: any;
		pause?: any;
		getContext?: any;
		toDataURL?: any;
		srcObject?: any;
	}

	interface HTMLIFrameElement {
		webkitRequestFullscreen?: any;
		msRequestFullscreen?: any;
	}

	interface HTMLInputElement {
		directory?: any;
	}

	interface Navigator {
		userLanguage?: string;
	}
}

export {};
