<script lang="ts">
	import { getContext, createEventDispatcher } from 'svelte';

	import { toast } from 'svelte-sonner';

	import { listCoderRepos, type CoderRepo } from '$lib/apis/coder';

	import Github from '$lib/components/icons/Github.svelte';

	const i18n = getContext('i18n');
	const dispatch = createEventDispatcher();

	export let token: string;
	// full_name of the repository currently loaded for coding (highlighted in the list)
	export let selectedRepo = '';

	let repos: CoderRepo[] = [];
	let query = '';
	let loading = false;
	let loadedOnce = false;
	let searchTimer: ReturnType<typeof setTimeout>;

	const refresh = async () => {
		loading = true;
		try {
			const res = await listCoderRepos(token, query || undefined);
			repos = res.repos ?? [];
		} catch (e: any) {
			toast.error(e?.message ?? 'Failed to load repositories');
		} finally {
			loading = false;
			loadedOnce = true;
		}
	};

	const handleQueryInput = () => {
		clearTimeout(searchTimer);
		searchTimer = setTimeout(refresh, 400);
	};

	// expose refresh to the parent via bind:this
	export { refresh };

	$: if (token && !loadedOnce) refresh();
</script>

<div class="flex flex-col gap-2">
	<input
		bind:value={query}
		on:input={handleQueryInput}
		placeholder={$i18n.t('Search a repository')}
		class="w-full rounded-xl bg-gray-50 dark:bg-gray-850 px-3 py-2 text-xs outline-hidden ring-1 ring-transparent focus:ring-gray-300 dark:focus:ring-gray-700"
	/>

	{#if loading}
		<div class="px-2 py-3 text-xs text-gray-500">{$i18n.t('Loading repositories')}…</div>
	{:else if repos.length === 0}
		<div class="px-2 py-3 text-xs text-gray-500">{$i18n.t('No repositories found')}</div>
	{:else}
		<div class="flex flex-col gap-1.5">
			{#each repos as r (r.full_name)}
				<button
					type="button"
					class="w-full text-left rounded-2xl border px-3.5 py-3 flex items-center gap-3 transition {selectedRepo === r.full_name
						? 'border-blue-400 dark:border-blue-600 bg-blue-50/50 dark:bg-blue-950/20'
						: 'border-gray-200 dark:border-gray-700 hover:bg-gray-50 dark:hover:bg-gray-800/60'}"
					on:click={() => dispatch('select', r)}
				>
					<Github className="size-5 shrink-0 text-gray-500" />
					<div class="flex-1 min-w-0">
						<div class="text-sm font-medium truncate text-black dark:text-white">{r.full_name}</div>
						<div class="text-[11px] text-gray-500 truncate">
							{$i18n.t('Default branch')}: {r.default_branch ?? '—'}
						</div>
					</div>
					<div class="flex items-center gap-1.5 shrink-0">
						{#if r.private}
							<span class="text-[10px] px-1.5 py-0.5 rounded bg-gray-100 dark:bg-gray-800 text-gray-500">private</span>
						{/if}
						{#if r.push_allowed}
							<span class="text-[10px] px-1.5 py-0.5 rounded bg-green-100 dark:bg-green-950/50 text-green-700 dark:text-green-400"
								>{$i18n.t('write')}</span
							>
						{/if}
						{#if selectedRepo === r.full_name}
							<span
								class="text-[10px] px-1.5 py-0.5 rounded bg-blue-100 dark:bg-blue-950/50 text-blue-700 dark:text-blue-400">{$i18n.t('loaded')}</span
							>
						{:else}
							<span class="text-[11px] text-gray-400">{$i18n.t('Load')}</span>
						{/if}
					</div>
				</button>
			{/each}
		</div>
	{/if}
</div>
