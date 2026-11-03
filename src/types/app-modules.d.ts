// Ambient declarations for SvelteKit $app/* modules (fallback when .svelte-kit types are absent)
declare module '$app/stores' {
	import type { Readable, Writable } from 'svelte/store';

	export interface Page<Params extends Record<string, string> = Record<string, string>> {
		url: URL;
		params: Params;
		searchParams: URLSearchParams;
		form: Record<string, any> | null;
		data: Record<string, any>;
		state: Record<string, any>;
		errors: Record<string, any> | null;
		status: number;
		maxage: number;
		requiresRefresh: boolean;
	}

	export const page: Readable<Page>;
	export const navigating: Readable<any>;
	export const preloading: Readable<boolean>;
	export const updated: Readable<boolean>;

	// open-webui augmentation stores (set up in +layout.svelte / stores)
	export const user: Writable<any>;
	export const config: Writable<any>;
	export const settings: Writable<any>;
	export const tags: Writable<any[]>;
	export const token: Writable<string | null>;
	export const theme: Writable<any>;
	export const mobile: Writable<boolean>;
}

declare module '$app/navigation' {
	export function goto(
		url: string | URL,
		opts?: {
			noScroll?: boolean;
			replaceState?: boolean;
			noscroll?: boolean;
			keepFocus?: boolean;
			label?: string;
			metadata?: Record<string, any>;
			state?: Record<string, any>;
			resolve?: (url: URL) => URL;
			invalidateAll?: boolean;
		}
	): Promise<void>;
	export function invalidate(
		...dependencies: Array<string | ((url: URL) => boolean)>
	): Promise<void>;
	export function invalidateAll(): Promise<void>;
	export function beforeNavigate(
		fn: (navigation: { cancel: () => void; willUnload: boolean; to: any; from: any }) => void | Promise<void>
	): void;
	export function onNavigate(fn: (navigation: any) => void): () => void;
	export function applyAction(result: any): Promise<void> | void;
}

declare module '$app/paths' {
	export function resolve(path: string, params?: Record<string, string>): string;
	export function resolveRoute(...args: any[]): string;
	export const base: string;
	export const assets: string;
}

declare module '$app/environment' {
	export const browser: boolean;
	export const dev: boolean;
	export const building: boolean;
	export const version: string;
}

declare module '$app/forms' {
	export function enhance(form: HTMLFormElement, formAction?: any, handlers?: any): () => void;
	export function deserialize(form: HTMLFormElement): Record<string, any>;
	export function serialize(form: HTMLFormElement, options?: any): URLSearchParams;
	export function stripFormData(
		data: Record<string, any>,
		files: Array<File>,
		removeFiles?: boolean
	): Record<string, any>;
}

declare module '$app/state' {
	export const page: any;
	export const navigating: any;
	export const preloading: any;
	export const updated: any;
}

declare module '$app/server' {
	export function event(...args: any[]): any;
	export function request(...args: any[]): any;
}
