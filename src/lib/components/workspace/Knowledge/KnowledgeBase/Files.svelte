<script lang="ts">
	import dayjs from '$lib/dayjs';
	import duration from 'dayjs/plugin/duration';
	import relativeTime from 'dayjs/plugin/relativeTime';

	dayjs.extend(duration);
	dayjs.extend(relativeTime);

	import { getContext } from 'svelte';
	const i18n = getContext('i18n');

	import { capitalizeFirstLetter, formatFileSize } from '$lib/utils';

	import { WEBUI_BASE_URL } from '$lib/constants';

	import Tooltip from '$lib/components/common/Tooltip.svelte';
	import Dropdown from '$lib/components/common/Dropdown.svelte';
	import DocumentPage from '$lib/components/icons/DocumentPage.svelte';
	import EllipsisHorizontal from '$lib/components/icons/EllipsisHorizontal.svelte';
	import Download from '$lib/components/icons/Download.svelte';
	import GarbageBin from '$lib/components/icons/GarbageBin.svelte';
	import Pencil from '$lib/components/icons/Pencil.svelte';
	import Spinner from '$lib/components/common/Spinner.svelte';
	import Folder from '$lib/components/icons/Folder.svelte';
	import DirectoryRow from './DirectoryRow.svelte';

	export let knowledge = null;
	export let selectedFileId = null;
	export let files = [];
	export let directories = [];

	export let onClick = (fileId) => {};
	export let onDelete = (fileId) => {};
	export let onRename = (fileId: string, name: string) => {};
	export let onNavigateDirectory = (directoryId: string) => {};
	export let onRenameDirectory = (id: string, name: string) => {};
	export let onDeleteDirectory = (id: string) => {};
	export let onMoveFileToDirectory = (fileId: string, directoryId: string) => {};
	export let onMoveDirectoryToDirectory = (dirId: string, targetDirectoryId: string) => {};
	export let onMoveFile = (fileId: string) => {};
	export let onCancelEmbedding = (fileId: string) => {};

	let editingFileId: string | null = null;
	let editName = '';
	let editInput: HTMLInputElement;

	const startRename = (file: any) => {
		editingFileId = file?.id ?? file?.tempId;
		editName = file?.name ?? file?.meta?.name ?? '';
		setTimeout(() => editInput?.select(), 0);
	};

	const submitRename = () => {
		if (editingFileId && editName.trim()) {
			onRename(editingFileId, editName.trim());
		}
		editingFileId = null;
	};

	const cancelRename = () => {
		editingFileId = null;
	};

	const isInFlight = (file: any) =>
		file?.status === 'uploading' || file?.status === 'processing' || file?.status === 'pending';

	const progressPercent = (file: any) => {
		const percent = file?.progress?.percent;
		if (typeof percent !== 'number' || Number.isNaN(percent)) return null;
		return Math.max(0, Math.min(100, Math.round(percent * 100)));
	};

	const progressLabel = (file: any) => {
		const progress = file?.progress;
		// The server labels its phase 'embedding'; anything that reports chunk counts
		// is past the transfer stage and worth showing as granular progress.
		if (progress?.total_chunks) {
			return $i18n.t('Embedding {{processed}}/{{total}} chunks', {
				processed: progress.processed_chunks ?? 0,
				total: progress.total_chunks
			});
		}
		if (progress?.phase === 'uploading') return $i18n.t('Uploading...');
		return $i18n.t('Processing...');
	};
</script>

<div class=" max-h-full flex flex-col w-full gap-[0.5px]">
	<!-- Directories first -->
	{#each directories as dir (dir.id)}
		<DirectoryRow
			directory={dir}
			writeAccess={knowledge?.write_access}
			onNavigate={(id) => onNavigateDirectory(id)}
			onRename={(id, name) => onRenameDirectory(id, name)}
			onDelete={(id) => onDeleteDirectory(id)}
			onFileDrop={(fileId, directoryId) => onMoveFileToDirectory(fileId, directoryId)}
			onDirDrop={(dirId, targetId) => onMoveDirectoryToDirectory(dirId, targetId)}
		/>
	{/each}

	<!-- Files -->
	{#each files as file (file?.id ?? file?.itemId ?? file?.tempId)}
		<div
			class=" flex cursor-pointer w-full px-2 bg-transparent dark:hover:bg-gray-850/50 hover:bg-white rounded-xl transition {selectedFileId
				? ''
				: 'hover:bg-gray-100 dark:hover:bg-gray-850'}"
			draggable="true"
			on:dragstart={(e) => {
				const fileId = file?.id ?? file?.tempId;
				if (fileId) {
					e.dataTransfer?.setData('application/x-kb-file-move', JSON.stringify({ fileId }));
				}
			}}
		>
			<div class="flex items-center">
				{#if file?.status !== 'uploading'}
					<button
						class="p-1 rounded-full transition"
						type="button"
						on:click={() => {
							let fileId = file?.id ?? file?.tempId;
							onClick(fileId);
						}}
					>
						<DocumentPage className="size-3.5" />
					</button>
				{:else}
					<Spinner className="size-3.5" />
				{/if}
			</div>

			<button
				class="relative flex items-center gap-1 rounded-xl p-2 text-left flex-1 justify-between"
				type="button"
				on:click={() => {
					if (editingFileId) return;
					onClick(file?.id ?? file?.tempId);
				}}
				on:dblclick={() => {
					if (knowledge?.write_access) startRename(file);
				}}
			>
				<div>
					<div class="flex gap-2 items-center line-clamp-1">
						{#if editingFileId === (file?.id ?? file?.tempId)}
							<!-- svelte-ignore a11y-autofocus -->
							<input
								bind:this={editInput}
								bind:value={editName}
								class="text-sm w-full bg-transparent border-none outline-hidden"
								on:keydown={(e) => {
									if (e.key === 'Enter') submitRename();
									if (e.key === 'Escape') cancelRename();
									if (e.key === ' ') e.stopPropagation();
								}}
								on:keyup={(e) => {
									if (e.key === ' ') e.stopPropagation();
								}}
								on:blur={submitRename}
								on:click={(e) => e.stopPropagation()}
								autofocus
							/>
						{:else}
							<div class="line-clamp-1 text-sm">
								{file?.name ?? file?.meta?.name}
								{#if file?.meta?.size}
									<span class="text-xs text-gray-500">{formatFileSize(file?.meta?.size)}</span>
								{/if}
							</div>
						{/if}
					</div>

					{#if isInFlight(file)}
						{@const percent = progressPercent(file)}
						<div class="flex items-center gap-2 pt-1">
							<div class="flex-1 min-w-[50px] h-1 rounded-full bg-gray-100 dark:bg-gray-800 overflow-hidden">
								<div
									class="h-full rounded-full bg-gray-700 dark:bg-gray-300 transition-all duration-300"
									style="width: {percent ?? 0}%"
								></div>
							</div>
							<div class="text-[10px] text-gray-500 dark:text-gray-400 shrink-0">
								{progressLabel(file)}
								{#if percent !== null}<span class="ml-1">{percent}%</span>{/if}
							</div>
						</div>
					{/if}
				</div>

				<div class="flex items-center gap-2 shrink-0">
					{#if file?.updated_at}
						<Tooltip content={dayjs(file.updated_at * 1000).format('LLLL')}>
							<div class="text-xs text-gray-400">
								{dayjs(file.updated_at * 1000).fromNow()}
							</div>
						</Tooltip>
					{/if}

					{#if file?.user}
						<Tooltip
							content={file?.user?.email ?? $i18n.t('Deleted User')}
							className="flex shrink-0"
							placement="top-start"
						>
							<div class="shrink-0 text-gray-500">
								{$i18n.t('By {{name}}', {
									name: capitalizeFirstLetter(
										file?.user?.name ?? file?.user?.email ?? $i18n.t('Deleted User')
									)
								})}
							</div>
						</Tooltip>
					{/if}
				</div>
			</button>

			{#if knowledge?.write_access}
				<div class="flex items-center">
					<Dropdown align="end" sideOffset={4}>
						<button
							class="p-1 rounded-full hover:bg-gray-100 dark:hover:bg-gray-850 transition"
							type="button"
						>
							<EllipsisHorizontal className="size-3.5" />
						</button>

						<div slot="content">
							<div
								class="min-w-[140px] rounded-2xl p-1 z-[9999999] bg-white dark:bg-gray-850 dark:text-white shadow-lg border border-gray-100 dark:border-gray-800"
							>
								<button
									type="button"
									class="select-none flex rounded-xl py-1.5 px-3 w-full hover:bg-gray-50 dark:hover:bg-gray-800 transition items-center gap-2 text-sm"
									on:click={() => {
										startRename(file);
									}}
								>
									<Pencil className="size-3.5" />
									{$i18n.t('Rename')}
								</button>
								<button
									type="button"
									class="select-none flex rounded-xl py-1.5 px-3 w-full hover:bg-gray-50 dark:hover:bg-gray-800 transition items-center gap-2 text-sm"
									on:click={() => {
										let fileId = file?.id ?? file?.tempId;
										window.open(`${WEBUI_BASE_URL}/api/v1/files/${fileId}/content`, '_blank');
									}}
								>
									<Download className="size-3.5" />
									{$i18n.t('Download')}
								</button>
								{#if file?.status === 'uploading' || file?.status === 'processing' || file?.status === 'pending'}
								<button
									type="button"
									class="select-none flex rounded-xl py-1.5 px-3 w-full hover:bg-gray-50 dark:hover:bg-gray-800 transition items-center gap-2 text-sm text-red-500 dark:text-red-400"
									on:click={() => {
										onCancelEmbedding(file?.id ?? file?.itemId ?? file?.tempId);
									}}
								>
									<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="size-3.5">
										<circle cx="12" cy="12" r="10" />
										<line x1="15" y1="9" x2="9" y2="15" />
										<line x1="9" y1="9" x2="15" y2="15" />
									</svg>
									{$i18n.t('Cancel embedding')}
								</button>
								{:else}
								<button
									type="button"
									class="select-none flex rounded-xl py-1.5 px-3 w-full hover:bg-gray-50 dark:hover:bg-gray-800 transition items-center gap-2 text-sm"
									on:click={() => {
										onMoveFile(file?.id ?? file?.tempId);
									}}
								>
									<Folder className="size-3.5" />
									{$i18n.t('Move to folder')}
								</button>
								{/if}
								<button
									type="button"
									class="select-none flex rounded-xl py-1.5 px-3 w-full hover:bg-gray-50 dark:hover:bg-gray-800 transition items-center gap-2 text-sm"
									on:click={() => {
										onDelete(file?.id ?? file?.tempId);
									}}
								>
									<GarbageBin className="size-3.5" />
									{$i18n.t('Delete')}
								</button>
							</div>
						</div>
					</Dropdown>
				</div>
			{/if}
		</div>
	{/each}
</div>
