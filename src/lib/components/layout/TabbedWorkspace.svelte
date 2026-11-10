<script lang="ts">
	import { onMount, getContext } from 'svelte';
	import type { Writable } from 'svelte/store';
	import type { i18n as i18nType } from 'i18next';

	import ChatBubbleDotted from '$lib/components/icons/ChatBubbleDotted.svelte';
	import Code from '$lib/components/icons/Code.svelte';
	import FolderOpen from '$lib/components/icons/FolderOpen.svelte';
	import Photo from '$lib/components/icons/Photo.svelte';
	import Mic from '$lib/components/icons/Mic.svelte';
	import Search from '$lib/components/icons/Search.svelte';
	import XMark from '$lib/components/icons/XMark.svelte';
	import Plus from '$lib/components/icons/Plus.svelte';
	import ArrowLeft from '$lib/components/icons/ArrowLeft.svelte';
	import ArrowRight from '$lib/components/icons/ArrowRight.svelte';
	import Refresh from '$lib/components/icons/Refresh.svelte';

	const i18n: Writable<i18nType> = getContext<Writable<i18nType>>('i18n');

	type TabId = 'chat' | 'code' | 'files' | 'preview' | 'terminal' | 'browser';

	interface Tab {
		id: TabId;
		label: string;
		icon: string;
		closeable: boolean;
	}

	const availableTabs: Tab[] = [
		{ id: 'chat', label: 'Chat', icon: 'ChatBubble', closeable: false },
		{ id: 'code', label: 'Code', icon: 'Code', closeable: true },
		{ id: 'files', label: 'Files', icon: 'FolderOpen', closeable: true },
		{ id: 'preview', label: 'Preview', icon: 'Photo', closeable: true },
		{ id: 'terminal', label: 'Terminal', icon: 'Mic', closeable: true },
		{ id: 'browser', label: 'Browser', icon: 'Search', closeable: true }
	];

	let activeTab: TabId = 'chat';
	let openTabs: TabId[] = ['chat'];

	const addTab = (tabId: TabId) => {
		if (!openTabs.includes(tabId)) {
			openTabs = [...openTabs, tabId];
		}
		activeTab = tabId;
	};

	const closeTab = (tabId: TabId) => {
		if (tabId === 'chat') return;
		openTabs = openTabs.filter((id) => id !== tabId);
		if (activeTab === tabId) {
			activeTab = openTabs.length > 0 ? openTabs[0] : 'chat';
		}
	};

	const setActiveTab = (tabId: TabId) => {
		activeTab = tabId;
	};

	const getTab = (tabId: TabId) => availableTabs.find((t) => t.id === tabId);

	onMount(() => {
		// Initialize workspace
	});
</script>

<div class="tabbed-workspace h-full w-full flex flex-col overflow-hidden">
	<!-- Tab Bar -->
	<div
		class="flex items-center gap-0 border-b border-gray-200 dark:border-gray-800 bg-gray-50 dark:bg-gray-900/50 z-10"
	>
		{#each openTabs as tabId}
			{@const tab = getTab(tabId)}
			{#if tab}
				<div class="flex items-center gap-0 relative">
					<button
						class={`flex items-center gap-2 px-4 py-2.5 text-sm font-medium transition border-b-2 ${
							activeTab === tabId
								? 'border-blue-500 dark:border-blue-400 text-blue-600 dark:text-blue-400 bg-blue-50 dark:bg-blue-900/20'
								: 'text-gray-600 dark:text-gray-400 hover:text-gray-900 dark:hover:text-gray-100 hover:bg-gray-100 dark:hover:bg-gray-800/50'
						}`}
						on:click={() => setActiveTab(tabId)}
						aria-label={tab.label}
					>
						<div class="flex items-center justify-center size-4">
							{#if tab.icon === 'ChatBubble'}
								<ChatBubbleDotted className="size-4" strokeWidth="1.5" />
							{:else if tab.icon === 'Code'}
								<Code className="size-4" strokeWidth="1.5" />
							{:else if tab.icon === 'FolderOpen'}
								<FolderOpen className="size-4" strokeWidth="1.5" />
							{:else if tab.icon === 'Photo'}
								<Photo className="size-4" strokeWidth="1.5" />
							{:else if tab.icon === 'Mic'}
								<Mic className="size-4" strokeWidth="1.5" />
							{:else if tab.icon === 'Search'}
								<Search className="size-4" strokeWidth="1.5" />
							{/if}
						</div>
						<span>{tab.label}</span>
					</button>
					{#if tab.closeable && activeTab === tabId}
						<button
							class="ml-1 p-1 text-gray-400 hover:text-red-500 dark:hover:text-red-400 transition rounded hover:bg-red-100 dark:hover:bg-red-900/30"
							on:click|stopPropagation={() => closeTab(tabId)}
							aria-label={`Close ${tab.label} tab`}
						>
							<XMark className="size-3.5" strokeWidth="1.5" />
						</button>
					{/if}
				</div>
			{/if}
		{/each}
		<button
			class="flex items-center gap-2 px-3 py-2.5 text-sm text-gray-600 dark:text-gray-400 hover:text-blue-600 dark:hover:text-blue-400 hover:bg-blue-50 dark:bg-blue-900/20 transition rounded-l"
			on:click={() => {
				const nextTab: TabId = openTabs.includes('code')
					? 'code'
					: openTabs.includes('files')
						? 'files'
						: openTabs.includes('preview')
							? 'preview'
							: openTabs.includes('terminal')
								? 'terminal'
								: 'browser';
				addTab(nextTab);
			}}
			aria-label="Add new tab"
		>
			<Plus className="size-4" strokeWidth="1.5" />
			<span class="ml-1 hidden sm:inline">New Tab</span>
		</button>
	</div>

	<!-- Tab Content -->
	<div class="flex-1 overflow-hidden relative">
		{#if activeTab === 'chat'}
			<slot name="chat" />
		{:else if activeTab === 'code'}
			<div class="h-full w-full bg-gray-50 dark:bg-gray-950 flex flex-col">
				<div
					class="p-4 border-b border-gray-200 dark:border-gray-800 flex items-center justify-between"
				>
					<h3 class="text-sm font-medium text-gray-900 dark:text-white">Code Editor</h3>
					<button class="text-xs text-blue-600 dark:text-blue-400 hover:underline"
						>Open in fullscreen</button
					>
				</div>
				<div class="flex-1 overflow-hidden">
					<slot name="code" />
				</div>
			</div>
		{:else if activeTab === 'files'}
			<div class="h-full w-full bg-gray-50 dark:bg-gray-950 flex flex-col">
				<div
					class="p-4 border-b border-gray-200 dark:border-gray-800 flex items-center justify-between"
				>
					<h3 class="text-sm font-medium text-gray-900 dark:text-white">Files</h3>
				</div>
				<div class="flex-1 overflow-hidden">
					<slot name="files" />
				</div>
			</div>
		{:else if activeTab === 'preview'}
			<div class="h-full w-full bg-gray-50 dark:bg-gray-950 flex flex-col">
				<div
					class="p-4 border-b border-gray-200 dark:border-gray-800 flex items-center justify-between"
				>
					<h3 class="text-sm font-medium text-gray-900 dark:text-white">Preview</h3>
				</div>
				<div class="flex-1 overflow-hidden">
					<slot name="preview" />
				</div>
			</div>
		{:else if activeTab === 'terminal'}
			<div class="h-full w-full bg-black text-green-400 flex flex-col">
				<div class="p-3 border-b border-gray-800 flex items-center justify-between text-xs">
					<span>Terminal</span>
					<div class="flex gap-2">
						<button class="px-2 py-1 rounded hover:bg-gray-700">New</button>
						<button class="px-2 py-1 rounded hover:bg-gray-700">Split</button>
					</div>
				</div>
				<div class="flex-1 overflow-hidden font-mono text-sm">
					<slot name="terminal" />
				</div>
			</div>
		{:else if activeTab === 'browser'}
			<div class="h-full w-full bg-white dark:bg-gray-900 flex flex-col">
				<div
					class="p-3 border-b border-gray-200 dark:border-gray-800 flex items-center justify-between"
				>
					<div class="flex items-center gap-2">
						<button class="p-2 rounded hover:bg-gray-100 dark:hover:bg-gray-800">
							<ArrowLeft className="size-4" strokeWidth="1.5" />
						</button>
						<button class="p-2 rounded hover:bg-gray-100 dark:hover:bg-gray-800">
							<ArrowRight className="size-4" strokeWidth="1.5" />
						</button>
						<button class="p-2 rounded hover:bg-gray-100 dark:hover:bg-gray-800">
							<Refresh className="size-4" strokeWidth="1.5" />
						</button>
						<input name="field"
							type="text"
							placeholder="Enter URL..."
							class="flex-1 px-3 py-1.5 rounded border border-gray-300 dark:border-gray-700 bg-white dark:bg-gray-800 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
						/>
					</div>
					<button
						class="px-3 py-1.5 text-sm font-medium text-blue-600 dark:text-blue-400 hover:bg-blue-50 dark:hover:bg-blue-900/20 rounded"
					>
						Open
					</button>
				</div>
				<div class="flex-1 overflow-hidden relative">
					<iframe class="w-full h-full border-0" src="about:blank" title="Browser preview"></iframe>
					<slot name="browser" />
				</div>
			</div>
		{/if}
	</div>
</div>
