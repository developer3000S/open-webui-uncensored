<script lang="ts">
	import type i18nType from 'i18next';
	import { getContext } from 'svelte';
	const i18n = getContext<i18nType>('i18n');

	import { WEBUI_BASE_URL } from '$lib/constants';
	import { safeImageUrl } from '$lib/utils/safeImageUrl';

	import { settings } from '$lib/stores';
	import ImagePreview from './ImagePreview.svelte';
	import XMark from '$lib/components/icons/XMark.svelte';

	export let src: any = '';
	export let alt: any = '';
	export let className = ` w-full ${($settings?.highContrastMode ?? false) ? '' : 'outline-hidden focus:outline-hidden'}`;

	export let imageClassName: any = 'rounded-lg';
	export let dismissible: any = false;
	export let onDismiss = () => {};

	import type { Writable } from 'svelte/store';

	let _src = '';
	$: _src = safeImageUrl(src.startsWith('/') ? `${WEBUI_BASE_URL}${src}` : src);

	let showImagePreview = false;
</script>

<ImagePreview bind:show={showImagePreview} src={_src} {alt} />

<div class=" relative group w-fit flex items-center">
	<button
		class={className}
		on:click={() => {
			showImagePreview = true;
		}}
		aria-label={i18n.t('Show image preview')}
		type="button"
	>
		<img src={_src} {alt} class={imageClassName} draggable="false" data-cy="image" />
	</button>

	{#if dismissible}
		<div class=" absolute -top-1 -right-1">
			<button
				aria-label={i18n.t('Remove image')}
				class=" bg-white text-black border border-white rounded-full group-hover:visible invisible transition"
				type="button"
				on:click={() => {
					onDismiss();
				}}
			>
				<XMark className={'size-4'} />
			</button>
		</div>
	{/if}
</div>

<ImagePreview bind:show={showImagePreview} src={_src} {alt} />

<div class=" relative group w-fit flex items-center">
	<button
		class={className}
		on:click={() => {
			showImagePreview = true;
		}}
		aria-label={i18n.t('Show image preview')}
		type="button"
	>
		<img src={_src} {alt} class={imageClassName} draggable="false" data-cy="image" />
	</button>

	{#if dismissible}
		<div class=" absolute -top-1 -right-1">
			<button
				aria-label={i18n.t('Remove image')}
				class=" bg-white text-black border border-white rounded-full group-hover:visible invisible transition"
				type="button"
				on:click={() => {
					onDismiss();
				}}
			>
				<XMark className={'size-4'} />
			</button>
		</div>
	{/if}
</div>
