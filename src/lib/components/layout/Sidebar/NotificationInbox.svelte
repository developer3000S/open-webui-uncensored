<script lang="ts">
	import { onMount, getContext } from 'svelte';
	import type { Writable } from 'svelte/store';
	import type { i18n as i18nType } from 'i18next';

	import {
		getNotifications,
		getUnreadNotificationCount,
		markNotificationRead,
		markAllNotificationsRead
	} from '$lib/apis/notifications';
	import ChatBubbleDotted from '$lib/components/icons/ChatBubbleDotted.svelte';
	import InfoCircle from '$lib/components/icons/InfoCircle.svelte';

	const i18n: Writable<i18nType> = getContext<Writable<i18nType>>('i18n');

	let notifications: any[] = [];
	let unreadCount = 0;
	let isOpen = false;
	let loading = false;

	const token = localStorage.token;

	const loadNotifications = async () => {
		if (!token) return;
		loading = true;
		try {
			notifications = (await getNotifications(token, false, 20)) || [];
			const countRes = await getUnreadNotificationCount(token);
			unreadCount = countRes?.count ?? 0;
		} catch (e) {
			console.error('Failed to load notifications', e);
		} finally {
			loading = false;
		}
	};

	const toggleInbox = () => {
		isOpen = !isOpen;
		if (isOpen) {
			loadNotifications();
		}
	};

	const markRead = async (id: string) => {
		if (!token) return;
		try {
			await markNotificationRead(token, id);
			notifications = notifications.map((n) =>
				n.id === id ? { ...n, read: true } : n
			);
			const countRes = await getUnreadNotificationCount(token);
			unreadCount = countRes?.count ?? 0;
		} catch (e) {
			console.error('Failed to mark notification as read', e);
		}
	};

	const markAllRead = async () => {
		if (!token) return;
		try {
			await markAllNotificationsRead(token);
			notifications = notifications.map((n) => ({ ...n, read: true }));
			unreadCount = 0;
		} catch (e) {
			console.error('Failed to mark all notifications as read', e);
		}
	};

	onMount(() => {
		if (token) {
			getUnreadNotificationCount(token).then((c) => {
				unreadCount = c?.count ?? 0;
			}).catch(() => {});
		}
	});
</script>

<button
	class="relative p-2 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-850 transition"
	on:click={toggleInbox}
	aria-label={$i18n.t('Notifications')}
>
		<div class="relative">
			<InfoCircle className="size-5" strokeWidth="1.5" />
		{#if unreadCount > 0}
			<span
				class="absolute -top-1 -right-1 flex h-4 w-4 items-center justify-center rounded-full bg-red-500 text-white text-xs font-bold"
				aria-label={$i18n.t('Unread notifications')}
			>
				{unreadCount > 9 ? '9+' : unreadCount}
			</span>
		{/if}
	</div>
</button>

{#if isOpen}
	<div
		class="fixed top-16 right-4 w-80 bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-700 rounded-lg shadow-lg z-50 flex flex-col"
		role="dialog"
		aria-modal="true"
		aria-label={$i18n.t('Notifications')}
	>
		<div class="p-4 border-b border-gray-100 dark:border-gray-700 flex items-center justify-between">
			<h2 class="text-lg font-semibold">{$i18n.t('Notifications')}</h2>
			<button
				class="text-sm hover:text-gray-600 dark:hover:text-gray-300 transition"
				on:click={markAllRead}
				disabled={unreadCount === 0}
			>
				{$i18n.t('Mark all as read')}
			</button>
		</div>

		<div class="p-4 overflow-y-auto max-h-[60vh] flex flex-col gap-3">
			{#if loading}
				<div class="text-center text-gray-500 animate-pulse">
					{$i18n.t('Loading...')}
				</div>
			{:else if notifications.length === 0}
				<div class="text-center text-gray-500 py-8">
					<p>{$i18n.t('No notifications')}</p>
				</div>
			{:else}
				{#each notifications as notification}
					<div
						class="p-3 rounded-lg hover:bg-gray-50 dark:hover:bg-gray-800 transition cursor-pointer border-l-4"
						class:border-blue-500={!notification.read}
						class:border-gray-200={notification.read}
						on:click={() => markRead(notification.id)}
					>
						<div class="flex items-start gap-2">
							<div class="flex-shrink-0 mt-0.5">
								<span
									class={notification.type === 'comment' ? 'text-blue-500 dark:text-blue-400' : notification.type === 'mention' ? 'text-purple-500 dark:text-purple-400' : notification.type === 'reply' ? 'text-green-500 dark:text-green-400' : notification.type === 'automation' ? 'text-orange-500 dark:text-orange-400' : 'text-gray-500 dark:text-gray-400'}
								>
									{#if notification.type === 'comment'}
										<ChatBubbleDotted className="size-4" strokeWidth="1.5" />
									{:else if notification.type === 'mention'}
										<ChatBubbleDotted className="size-4" strokeWidth="1.5" />
									{:else if notification.type === 'reply'}
										<ChatBubbleDotted className="size-4" strokeWidth="1.5" />
									{:else if notification.type === 'automation'}
										<ChatBubbleDotted className="size-4" strokeWidth="1.5" />
									{:else}
										<InfoCircle className="size-4" strokeWidth="1.5" />
									{/if}
								</span>
							</div>
							<div class="flex-1 min-w-0">
								<div class="flex items-center gap-1 mb-1">
									<span
										class="text-xs font-medium truncate"
										class:text-blue-500={notification.type === 'comment'}
										class:text-purple-500={notification.type === 'mention'}
										class:text-green-500={notification.type === 'reply'}
										class:text-orange-500={notification.type === 'automation'}
										class:text-gray-500={notification.type === 'system'}
									>
										{notification.type.charAt(0).toUpperCase() + notification.type.slice(1)}
									</span>
									{#if !notification.read}
										<span class="text-[10px] bg-blue-100 dark:bg-blue-900 text-blue-600 dark:text-blue-400 px-1.5 py-0.5 rounded">
											{$i18n.t('New')}
										</span>
									{/if}
								</div>
								<h3 class="text-sm font-semibold truncate text-gray-900 dark:text-gray-100">
									{notification.title}
								</h3>
								{#if notification.content}
									<p class="text-xs text-gray-500 dark:text-gray-400 truncate mt-0.5 line-clamp-2">
										{notification.content}
									</p>
								{/if}
								<div class="mt-2 text-[10px] text-gray-400">
									{new Date(notification.created_at * 1000).toLocaleString()}
								</div>
							</div>
						</div>
					</div>
				{/each}
			{/if}
		</div>

		<div class="p-3 border-t border-gray-100 dark:border-gray-700 bg-gray-50 dark:bg-gray-800/50">
			<button
				class="w-full py-2 px-4 rounded-lg text-sm font-medium text-gray-600 dark:text-gray-300 hover:bg-gray-200 dark:hover:bg-gray-700 transition"
				on:click={() => {
					isOpen = false;
				}}
			>
				{$i18n.t('Close')}
			</button>
		</div>
	</div>

	<div
		class="fixed inset-0 bg-black/50 z-40 backdrop-blur-sm"
		on:click={() => (isOpen = false)}
	></div>
{/if}
