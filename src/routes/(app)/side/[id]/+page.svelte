<script lang="ts">
	import { page } from '$app/state';

	import Chat from '$lib/components/chat/Chat.svelte';

	const chatId = page.params.id;
	const isSideChat = page.url.searchParams.get('side') === 'true';

	// Side chats are temporary conversations that disappear when the tab is closed.
	// They use the same Chat component but are marked as side chats in the UI.
</script>

<Chat chatIdProp={chatId} {isSideChat} />
