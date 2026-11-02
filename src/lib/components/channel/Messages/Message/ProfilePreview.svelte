<script lang="ts">
	import { LinkPreview } from 'bits-ui';
	import { getContext } from 'svelte';

	import type { Writable } from 'svelte/store';
	import type { i18n as i18nType } from 'i18next';
	const i18n = getContext<Writable<i18nType>>('i18n');
	import UserStatus from './UserStatus.svelte';
	import UserStatusLinkPreview from './UserStatusLinkPreview.svelte';

	export let user = null;

	export let align = 'center';
	export let side = 'right';
	export let sideOffset = 8;

	let openPreview = false;
</script>

<LinkPreview.Root openDelay={0} closeDelay={200} bind:open={openPreview}>
	<LinkPreview.Trigger class="flex items-center">
		<button
			type="button"
			class=" cursor-pointer no-underline! font-normal!"
			on:click={() => {
				openPreview = !openPreview;
			}}
		>
			<slot />
		</button>
	</LinkPreview.Trigger>

	<UserStatusLinkPreview id={user?.id} {openPreview} {side} {align} {sideOffset} />
</LinkPreview.Root>
