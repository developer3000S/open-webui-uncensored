<script lang="ts">
	import { onMount } from 'svelte';
	import { toast } from 'svelte-sonner';

	import Chat from '$lib/components/chat/Chat.svelte';

	onMount(() => {
		if (new URLSearchParams(window.location.search).get('error')) {
			toast.error(
				new URLSearchParams(window.location.search).get('error') || 'An unknown error occurred.'
			);
		}
	});
</script>

<Chat />
