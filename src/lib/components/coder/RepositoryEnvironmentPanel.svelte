<script lang="ts">
	import { getContext, createEventDispatcher } from 'svelte';

	import { toast } from 'svelte-sonner';

	import {
		listCoderRepos,
		listCoderOrganizations,
		validateCoderGitHubConnection,
		getCoderGitHubAppStatus,
		connectCoderGitHubAppInstallation,
		type CoderRepo,
		type CoderGitHubAppInstallation
	} from '$lib/apis/coder';

	import Github from '$lib/components/icons/Github.svelte';

	const i18n = getContext('i18n');
	const dispatch = createEventDispatcher();

	export let token: string;
	// full_name of the repository currently loaded for coding (highlighted in the list)
	export let selectedRepo = '';

	let repos: CoderRepo[] = [];
	let query = '';
	let org = '';
	let organizations: { login: string; avatar_url?: string }[] = [];
	let loading = false;
	let loadedOnce = false;
	let errored = false;
	let searchTimer: ReturnType<typeof setTimeout>;

	// §D: connection validation state
	let validating = false;
	let validation: { valid: boolean; login?: string; warning?: string | null } | null = null;

	// §D: GitHub App installations state
	let appStatus: { configured: boolean; install_url: string | null; installations: CoderGitHubAppInstallation[] } | null = null;
	let appLoading = false;
	let connectingInstallation = '';

	const refresh = async () => {
		loading = true;
		try {
			const res = await listCoderRepos(token, query || undefined, org || undefined);
			repos = res.repos ?? [];
			errored = false;
		} catch (e: any) {
			repos = [];
			errored = true;
			toast.error(e?.detail?.message ?? e?.message ?? 'Failed to load repositories');
		} finally {
			loading = false;
			loadedOnce = true;
		}
	};

	const loadOrganizations = async () => {
		try {
			const res = await listCoderOrganizations(token);
			organizations = res.organizations ?? [];
		} catch (e) {
			organizations = [];
		}
	};

	const handleQueryInput = () => {
		clearTimeout(searchTimer);
		searchTimer = setTimeout(refresh, 400);
	};

	const handleOrgChange = () => {
		refresh();
	};

	const handleValidate = async () => {
		validating = true;
		validation = null;
		try {
			const res = await validateCoderGitHubConnection(token);
			validation = res;
			if (res.valid) {
				toast.success(`${i18n.t('Connection is valid')} (${res.login ?? ''})`);
			} else {
				toast.error(res.warning ?? i18n.t('Connection is invalid'));
			}
			// a valid OAuth connection may grant org access — refresh the filter list
			loadOrganizations();
		} catch (e: any) {
			validation = { valid: false, warning: e?.detail?.message ?? e?.message ?? 'Validation failed' };
			toast.error(validation.warning);
		} finally {
			validating = false;
		}
	};

	const loadAppStatus = async () => {
		appLoading = true;
		try {
			appStatus = await getCoderGitHubAppStatus(token);
		} catch (e) {
			appStatus = null;
		} finally {
			appLoading = false;
		}
	};

	const connectInstallation = async (installationId: string) => {
		connectingInstallation = installationId;
		try {
			const res = await connectCoderGitHubAppInstallation(token, installationId);
			toast.success(`${i18n.t('GitHub App connected')}: ${res.github_login ?? installationId}`);
			await Promise.all([refresh(), loadOrganizations()]);
		} catch (e: any) {
			toast.error(e?.detail?.message ?? e?.message ?? 'Failed to connect installation');
		} finally {
			connectingInstallation = '';
		}
	};

	// expose refresh to the parent via bind:this
	export { refresh };

	$: if (token && !loadedOnce) {
		refresh();
		loadOrganizations();
		loadAppStatus();
	}
</script>

<div class="flex flex-col gap-2">
	<div class="flex items-center gap-1.5">
		<input
			bind:value={query}
			on:input={handleQueryInput}
			placeholder={$i18n.t('Search a repository')}
			class="flex-1 min-w-0 rounded-xl bg-gray-50 dark:bg-gray-850 px-3 py-2 text-xs outline-hidden ring-1 ring-transparent focus:ring-gray-300 dark:focus:ring-gray-700"
		/>
		<button
			type="button"
			class="shrink-0 rounded-xl border border-gray-200 dark:border-gray-700 px-2.5 py-2 text-xs text-gray-600 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-800 disabled:opacity-50"
			on:click={handleValidate}
			disabled={validating}
			title={$i18n.t('Check GitHub connection validity')}
		>
			{#if validating}…{:else}{$i18n.t('Check')}{/if}
		</button>
	</div>

	{#if validation}
		<div class="px-2 py-1 text-[11px] {validation.valid ? 'text-green-600 dark:text-green-400' : 'text-red-500'}">
			{validation.valid ? $i18n.t('Connection is valid') : (validation.warning ?? $i18n.t('Connection is invalid'))}
		</div>
	{/if}

	{#if organizations.length > 0}
		<select
			bind:value={org}
			on:change={handleOrgChange}
			class="w-full rounded-xl bg-gray-50 dark:bg-gray-850 px-3 py-2 text-xs outline-hidden ring-1 ring-transparent focus:ring-gray-300 dark:focus:ring-gray-700"
		>
			<option value="">{$i18n.t('All organizations & personal')}</option>
			{#each organizations as o (o.login)}
				<option value={o.login}>{o.login}</option>
			{/each}
		</select>
	{/if}

	{#if appStatus && appStatus.configured && appStatus.installations.length > 0}
		<div class="flex flex-col gap-1 rounded-xl border border-gray-200 dark:border-gray-700 px-2.5 py-2">
			<div class="text-[10px] uppercase tracking-wide text-gray-400">{$i18n.t('GitHub App installations')}</div>
			{#each appStatus.installations as inst (inst.installation_id)}
				<button
					type="button"
					class="flex items-center justify-between gap-2 text-xs text-left text-gray-600 dark:text-gray-300 hover:text-black dark:hover:text-white disabled:opacity-50"
					on:click={() => connectInstallation(inst.installation_id)}
					disabled={connectingInstallation === inst.installation_id}
				>
					<span class="truncate">{inst.account_login ?? inst.installation_id}</span>
					<span class="shrink-0 text-[10px] text-gray-400">{connectingInstallation === inst.installation_id ? '…' : $i18n.t('Use')}</span>
				</button>
			{/each}
		</div>
	{:else if appStatus && appStatus.configured && appStatus.install_url}
		<a
			href={appStatus.install_url}
			target="_blank"
			rel="noopener noreferrer"
			class="rounded-xl border border-dashed border-gray-300 dark:border-gray-600 px-3 py-2 text-xs text-blue-500 hover:bg-gray-50 dark:hover:bg-gray-800/60"
		>
			{$i18n.t('Install the GitHub App on your repositories')} →
		</a>
	{/if}

	{#if loading}
		<div class="px-2 py-3 text-xs text-gray-500">{$i18n.t('Loading repositories')}…</div>
	{:else if repos.length === 0}
		<div class="px-2 py-3 text-xs text-gray-500">
			{#if errored}
				{$i18n.t('Failed to load repositories.')}
				<button type="button" class="underline text-blue-500" on:click={refresh}>{$i18n.t('Try again')}</button>
			{:else if query}
				{$i18n.t('No repositories found')}
			{:else}
				{$i18n.t('No repositories found')} — {$i18n.t('reconnect your GitHub account with the repo permission, then press Refresh')}
			{/if}
		</div>
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
