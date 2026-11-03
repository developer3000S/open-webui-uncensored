<script lang="ts">
	import { onMount, getContext } from 'svelte';
	import Message from './Message.svelte';

	import type { Writable } from 'svelte/store';
	
	export let messages: any = [];
	export let onInsert = (content: string) => {};
</script>

<div class="space-y-3 pb-12">
	{#each messages as message, idx}
		<Message
			{message}
			{idx}
			onInsert={() => {
				onInsert(message?.content ?? '');
			}}
			onEdit={() => {
				messages = messages.map((msg, messageIdx) => {
					if (messageIdx === idx) {
						return { ...msg, edit: true };
					}
					return msg;
				});
			}}
			onDelete={() => {
				messages = messages.filter((message, messageIdx) => messageIdx !== idx);
			}}
		/>
	{/each}
</div>
