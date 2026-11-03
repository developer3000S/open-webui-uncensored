<script lang="ts">
	import { createEventDispatcher } from 'svelte';
	import TTSVoiceInput from './TTSVoiceInput.svelte';

	type Item = {
		id: string;
		name?: string;
		description?: string;
		meta?: {
			description?: string;
		};
	};

	export let items: Item[] = [];
	export let placeholder: any = '';
	export let id: any = 'typeahead-selector';
	export let className: any = 'w-full';
	const dispatch = createEventDispatcher<{ select: Item }>();
	let value = '';
</script>

<div class="mb-1 block">
	<TTSVoiceInput
		{id}
		voices={items}
		{placeholder}
		{className}
		bind:value
		on:select={(e) => {
			dispatch('select', e.detail);
			value = '';
		}}
	/>
</div>
