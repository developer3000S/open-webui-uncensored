<script lang="ts">
	import { createEventDispatcher } from 'svelte';
	import { getContext } from 'svelte';
import type { Writable } from 'svelte/store';
import type { i18n as i18nType } from 'i18next';
	const i18n = getContext<Writable<i18nType>>('i18n');

	import TagItem from './TagItem.svelte';
	const dispatch = createEventDispatcher();

	export let tags = [];
	export let disabled = false;
</script>

{#each tags as tag}
	<TagItem
		{tag}
		{disabled}
		onDelete={() => {
			dispatch('delete', tag.name);
		}}
	/>
{/each}
