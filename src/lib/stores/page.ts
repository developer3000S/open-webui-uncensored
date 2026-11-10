import { toStore } from 'svelte/store';
import type { Readable } from 'svelte/store';
import type { Page } from '$app/state';
import { page as pageState } from '$app/state';

// SvelteKit 3 removed `$app/stores` and `$app/state` is only reactive in runes
// mode. Most of this codebase still uses legacy `$:` statements, where reads of
// `page.*` are untracked and therefore never update after the first render.
// This compatibility store snapshots every reactive field of the page state so
// that legacy components can keep using `$page` (and stay reactive) on
// navigation.
export const page: Readable<Page> = toStore(() => ({
	url: pageState.url,
	params: pageState.params,
	route: pageState.route,
	status: pageState.status,
	error: pageState.error,
	data: pageState.data,
	state: pageState.state,
	shallow: pageState.shallow,
	form: pageState.form
}));
