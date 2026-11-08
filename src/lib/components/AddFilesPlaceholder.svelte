<script lang="ts">
	import type { i18n as i18nType } from 'i18next';
	import { getContext } from 'svelte';
	const i18n = getContext<Writable<i18nType>>('i18n');

	export let title: any = '';
	export let content: any = '';
	import type { Writable } from 'svelte/store';
</script>

<div class="px-3">
	<div class="text-center dark:text-white text-2xl font-medium z-50" role="heading" aria-level="2">
		{#if title}
			{title}
		{:else}
			{$i18n.t('Add Files')}
		{/if}
	</div>

	<slot
		><div class="px-2 mt-2 text-center text-gray-700 dark:text-gray-200 w-full">
			{#if content}
				{content}
			{:else}
				{$i18n.t('Drop any files here to upload')}
			{/if}
		</div>
	</slot>
</div>
