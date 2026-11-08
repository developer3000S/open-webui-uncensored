<script lang="ts">
	import { page } from '$app/state';

	import Chat from '$lib/components/chat/Chat.svelte';
</script>

<Chat chatIdProp={page.params.id} />
