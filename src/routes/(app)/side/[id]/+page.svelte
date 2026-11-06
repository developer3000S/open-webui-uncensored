<script lang="ts">
	import { page } from '$app/stores';

	import Chat from '$lib/components/chat/Chat.svelte';

	const { side } = $page.params;
	const chatId = $page.params.id;
	const isSideChat = side === 'true';

	// Side chats are temporary conversations that disappear when the tab is closed.
	// They use the same Chat component but are marked as side chats in the UI.
</script>

<Chat chatIdProp={chatId} isSideChat={isSideChat} />
