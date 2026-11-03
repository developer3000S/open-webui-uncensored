<script lang="ts">
	import { createEventDispatcher } from 'svelte';
	import { getContext } from 'svelte';
	import type { Writable } from 'svelte/store';
	
	import TagItem from './TagItem.svelte';
	const dispatch = createEventDispatcher();

	export let tags: any = [];
	export let disabled: any = false;
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
