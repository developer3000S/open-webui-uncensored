// See https://kit.svelte.dev/docs/types#app
// for information about these interfaces
// eslint-disable-next-line @typescript-eslint/no-unused-vars
declare const APP_VERSION: string;
// eslint-disable-next-line @typescript-eslint/no-unused-vars
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

	// ВАЖНО: здесь намеренно объявлены только те свойства, которых НЕТ в
	// lib.dom. Переобъявление существующих членов (например, `style` у
	// HTMLElement, `querySelectorAll` у Node, `style` у Element) вызывало
	// конфликты внутри lib.dom.d.ts и дублирующиеся index signature.
	// Новый код должен использовать точные типы (`HTMLInputElement` и т.п.),
	// а не полагаться на этот legacy-shim.
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
	}

	interface Element {
		click?: any;
		contentWindow?: any;
	}

	interface HTMLElement {
		value?: any;
		select?: any;
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
