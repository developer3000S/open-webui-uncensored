<script lang="ts">
	import { onMount } from 'svelte';
	import { page } from '$app/stores';
	import { goto } from '$app/navigation';
	import { tick } from 'svelte';
	import { createMessagesList } from '$lib/utils';
	import { chatId, settings, models, user, showSidebar, mobile } from '$lib/stores';

	let loaded = false;
	import { chats } from '$lib/stores';

	let history = chats;
	import { getChatByShareId } from '$lib/apis/chats';
	import { getUserInfoById } from '$lib/apis/users';
	import { getUserSettings } from '$lib/apis/users';
import { getModels } from '$lib/apis';
	import i18n from '$lib/i18n';

	let selectedModels = [''];

	$: messagesList = createMessagesList(history, history.currentId);

	$: if (page.params.id) {
		(async () => {
			if (await loadSharedChat()) {
				await tick();
				loaded.set(true);
			} else {
				await goto('/');
			}
		})();
	}

	const loadSharedChat = async () => {
		const userSettings = await getUserSettings(localStorage.token).catch((error) => {
			console.error(error);
			return null;
		});

		await models.set(
			await getModels(
				localStorage.token,
				config?.features?.enable_direct_connections ? $settings?.directConnections || {} : null
			)
		);
		await chatId.set(page.params.id);
		chat.set(
			await getChatByShareId(localStorage.token, $chatId).catch(async (error: any) => {
				await goto('/');
				return null;
			})
		);

		if (chat) {
			user.set(
				await getUserInfoById(localStorage.token, chat.user_id!).catch((error) => {
					console.error(error);
					return null;
				})
			);

			return true;
		}

		return false;
	};
</script>

{#if loaded}
	<div
		class="flex flex-col w-full h-screen max-h-[100dvh] transition-width duration-200 ease-in-out {showSidebar
			? 'md:max-w-[calc(100%-var(--sidebar-width))]'
			: ''} max-w-full"
	>
		<nav class="px-2.5 pt-1.5 backdrop-blur-xl w-full drag-region">
			<div class="flex items-center">
				{#if mobile}
					<div class="{showSidebar ? 'md:hidden' : ''} flex flex-none items-center self-end">
						<Tooltip
							content={showSidebar ? i18n.t('Close Sidebar') : i18n.t('Open Sidebar')}
							interactive={true}
						>
							<button
								id="sidebar-toggle-button"
								class="p-1.5 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-800 transition"
								on:click={() => {
									showSidebar.set(!showSidebar);
								}}
							>
								<div class="self-center p-1.5">
									<Sidebar />
								</div>
							</button>
						</Tooltip>
					</div>
				{/if}

				<div class="flex-1 flex justify-center">
					<h1 class="text-xl font-medium">
						{$i18n.t('Shared Chat')}
					</h1>
				</div>
			</div>
		</nav>

		<div class="flex-1 overflow-auto">
			<Chat
				chatIdProp={$chatId}
				chatTitle={chat?.title || $i18n.t('Shared Chat')}
				userInfo={user}
				{selectedModels}
				onModelSelect={(models) => {
					selectedModels = models;
				}}
			/>
		</div>
	</div>
{/if}
