// Ambient declarations for third-party modules without bundled types
declare module 'sortablejs' {
	export interface SortableEvent {
		oldIndex: number;
		newIndex: number;
		item: HTMLElement;
		to: HTMLElement;
		from: HTMLElement;
	}
	export interface SortableOptions {
		group?: string | object;
		disabled?: boolean;
		animation?: number;
		handle?: string;
		draggable?: string;
		onStart?: (evt: SortableEvent) => void;
		onEnd?: (evt: SortableEvent) => void;
		onAdd?: (evt: SortableEvent) => void;
		[key: string]: any;
	}
	export default class Sortable {
		constructor(el: HTMLElement, options?: SortableOptions);
		option(name: string, value?: any): any;
		destroy(): void;
		static create(el: HTMLElement, options: SortableOptions): Sortable;
	}
}

declare module '@sveltejs/svelte-virtual-list' {
	import type { SvelteComponentTyped } from 'svelte';
	export default class VirtualList extends SvelteComponentTyped<any, any, any> {}
}

declare module 'turndown' {
	export default class TurndownService {
		constructor(options?: any);
		turndown(html: string | Node): string;
		addRule(key: string, options: any): this;
		use(plugin: (service: TurndownService) => void): this;
		[key: string]: any;
	}
}

declare module '@joplin/turndown-plugin-gfm' {
	export const gfm: any;
	export const strikethrough: any;
	export const tables: any;
}

declare module 'sql.js' {
	const initSqlJs: (config?: any) => Promise<any>;
	export default initSqlJs;
}

declare module 'leaflet' {
	const L: any;
	export = L;
}

declare module 'file-saver' {
export function saveAs(data: Blob | File | string, filename?: string, options?: any): void;
const fileSaver: { saveAs: typeof saveAs };
export default fileSaver;
}
