<script lang="ts">
	import { createEventDispatcher, getContext } from 'svelte';
	import type { Writable } from 'svelte/store';
	import type { i18n as i18nType } from 'i18next';

	const i18n = getContext<Writable<i18nType>>('i18n');

	import Modal from '$lib/components/common/Modal.svelte';
	import Folder from '$lib/components/icons/Folder.svelte';

	const dispatch = createEventDispatcher();

	export let show = false;
	// All available directories in the current knowledge base (flat list)
	export let directories: Array<{ id: string; name: string; parent_id?: string | null }> = [];
	// ID of the item being moved (to prevent moving into itself)
	export let excludeId: string | null = null;
	// Label shown at the top
	export let title = '';

	let selectedDirectoryId: string | null = null;

	// Build a simple flat list excluding the item being moved
	$: availableDirectories = directories.filter((d) => d.id !== excludeId);

	function selectDirectory(id: string | null) {
		selectedDirectoryId = id;
	}

	function handleSubmit() {
		dispatch('move', { directoryId: selectedDirectoryId });
		show = false;
	}

	function handleCancel() {
		show = false;
		selectedDirectoryId = null;
	}

	// Reset selection when modal opens
	$: if (show) {
		selectedDirectoryId = null;
	}
</script>

<Modal bind:show size="sm">
	<div class="px-5 pt-4 pb-5">
		<div class="font-semibold text-base mb-4">
			{title || $i18n.t('Move to folder')}
		</div>

		<div class="flex flex-col gap-1 max-h-72 overflow-y-auto pr-1">
			<!-- Root option -->
			<button
				type="button"
				class="flex items-center gap-2.5 px-3 py-2 rounded-xl text-sm transition w-full text-left
					{selectedDirectoryId === null
					? 'bg-gray-100 dark:bg-gray-800 font-medium'
					: 'hover:bg-gray-50 dark:hover:bg-gray-850'}"
				on:click={() => selectDirectory(null)}
			>
				<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="size-4 shrink-0 text-gray-500">
					<path stroke-linecap="round" stroke-linejoin="round" d="M3 9l9-7 9 7v11a2 2 0 01-2 2H5a2 2 0 01-2-2z" />
					<polyline stroke-linecap="round" stroke-linejoin="round" points="9 22 9 12 15 12 15 22" />
				</svg>
				<span>{$i18n.t('Root (no folder)')}</span>
			</button>

			{#each availableDirectories as dir (dir.id)}
				<button
					type="button"
					class="flex items-center gap-2.5 px-3 py-2 rounded-xl text-sm transition w-full text-left
						{selectedDirectoryId === dir.id
						? 'bg-gray-100 dark:bg-gray-800 font-medium'
						: 'hover:bg-gray-50 dark:hover:bg-gray-850'}"
					on:click={() => selectDirectory(dir.id)}
				>
					<Folder className="size-4 shrink-0 text-gray-500" />
					<span class="truncate">{dir.name}</span>
				</button>
			{/each}

			{#if availableDirectories.length === 0}
				<div class="text-xs text-gray-400 px-3 py-2">
					{$i18n.t('No folders available')}
				</div>
			{/if}
		</div>

		<div class="flex justify-end gap-2 mt-5">
			<button
				type="button"
				class="px-4 py-2 rounded-xl text-sm hover:bg-gray-100 dark:hover:bg-gray-850 transition"
				on:click={handleCancel}
			>
				{$i18n.t('Cancel')}
			</button>
			<button
				type="button"
				class="px-4 py-2 rounded-xl text-sm bg-gray-900 text-white dark:bg-white dark:text-gray-900 hover:opacity-90 transition"
				on:click={handleSubmit}
			>
				{$i18n.t('Move here')}
			</button>
		</div>
	</div>
</Modal>
