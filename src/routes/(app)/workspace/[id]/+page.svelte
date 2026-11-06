<script lang="ts">
	import { page } from '$app/stores';
	import TabbedWorkspace from '$lib/components/layout/TabbedWorkspace.svelte';
	import Chat from '$lib/components/chat/Chat.svelte';

	const chatId = $page.params.id;
</script>

<TabbedWorkspace>
	<svelte:fragment slot="chat">
		<Chat chatIdProp={chatId} />
	</svelte:fragment>

	<svelte:fragment slot="code">
		<div class="p-4 text-gray-500 dark:text-gray-400 text-center h-full flex items-center justify-center">
			<p>Code editor tab — select a file to edit</p>
		</div>
	</svelte:fragment>

	<svelte:fragment slot="files">
		<div class="p-4 text-gray-500 dark:text-gray-400 text-center h-full flex items-center justify-center">
			<p>File browser — select a chat to view attached files</p>
		</div>
	</svelte:fragment>

	<svelte:fragment slot="preview">
		<div class="p-4 text-gray-500 dark:text-gray-400 text-center h-full flex items-center justify-center">
			<p>Preview tab — generated artifacts appear here</p>
		</div>
	</svelte:fragment>

	<svelte:fragment slot="terminal">
		<div class="p-4 text-gray-500 dark:text-gray-400 text-center h-full flex items-center justify-center">
			<p>Terminal — connect to a code execution environment</p>
		</div>
	</svelte:fragment>

	<svelte:fragment slot="browser">
		<div class="p-4 text-gray-500 dark:text-gray-400 text-center h-full flex items-center justify-center">
			<p>Browser tab — open websites and local dev servers</p>
		</div>
	</svelte:fragment>
</TabbedWorkspace>
