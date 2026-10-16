<script lang="ts">
	import { getContext } from 'svelte';

	import { toast } from 'svelte-sonner';

	import Modal from '$lib/components/common/Modal.svelte';
	import Spinner from '$lib/components/common/Spinner.svelte';
	import { generateUUID } from '$lib/utils';
	import DiffView from './DiffView.svelte';

	import {
		previewCoderExport,
		startCoderExport,
		type CoderChangeSet,
		type CoderDiffEntry,
		type CoderExportPreview
	} from '$lib/apis/coder';

	const i18n = getContext('i18n');

	export let show = false;
	export let token: string;
	export let owner = '';
	export let repo = '';
	export let baseBranch = '';
	export let changeset: CoderChangeSet = { files: [] };

	let branch = '';
	let commitMessage = '';
	let preview: CoderExportPreview | null = null;
	let loadingPreview = false;
	let exporting = false;
	let exportError: string | null = null;

	let result: { commit_sha?: string; pr_url?: string; pr_number?: string } | null = null;

	// regenerate idempotency key whenever the dialog opens with a new changeset
	let idempotencyKey = generateUUID();

	// NOTE: this reactive block must NOT depend on `commitMessage` — previously every
	// keystroke in the commit-message field re-ran it and wiped the branch name back to
	// "coder/changes". It now fires once per dialog open and resets all transient state.
	$: if (show) {
		idempotencyKey = generateUUID();
		preview = null;
		result = null;
		exportError = null;
		branch = `coder/${new Date().toISOString().slice(0, 10)}-${generateUUID().slice(0, 8)}`;
	}

	// Map GitHub/Coder API error codes to human-readable messages
	const describeError = (detail: any): string => {
		if (!detail) return 'Request failed';
		if (typeof detail === 'string') return detail;
		const code = detail.code ?? '';
		const msg = detail.message ?? '';
		const path = detail.path ? ` (${detail.path})` : '';
		switch (code) {
			case 'CODER_GITHUB_UNAUTHORIZED':
				return $i18n.t('Your GitHub connection has expired. Reconnect your account in the Environment tab, then try again.');
			case 'CODER_GITHUB_RATE_LIMIT':
				return $i18n.t('GitHub API rate limit exceeded. Try again in a few minutes.');
			case 'CODER_FORBIDDEN':
				return $i18n.t('Access denied by GitHub — your token may lack the required repository scopes (repo). Reconnect GitHub in the Environment tab.');
			case 'CODER_BRANCH_PROTECTED':
				return $i18n.t('The target branch is protected on GitHub. Export always pushes to a new branch and opens a pull request.');
			case 'CODER_CONFLICT':
				return $i18n.t('Conflict with the remote repository (the base branch moved). Run Preview again and retry.');
			case 'CODER_VALIDATION_FAILED':
				return `${$i18n.t('GitHub rejected the change set')}: ${msg}${path}`;
			case 'CODER_FILE_NOT_FOUND':
				return `${$i18n.t('File does not exist in the base branch')}${path}`;
			case 'CODER_FILE_EXISTS':
				return `${$i18n.t('File already exists in the base branch')}${path}`;
			case 'CODER_GITHUB_UNAVAILABLE':
				return $i18n.t('GitHub API is unreachable. Check server network connectivity and retry.');
			default:
				return msg ? `${code ? code + ': ' : ''}${msg}${path}` : 'Request failed';
		}
	};

	const runPreview = async () => {
		loadingPreview = true;
		preview = null;
		exportError = null;
		try {
			preview = await previewCoderExport(token, {
				owner,
				repo,
				base_branch: baseBranch,
				branch,
				commit_message: commitMessage,
				changeset,
				idempotency_key: idempotencyKey
			});
		} catch (e: any) {
			const msg = describeError(e?.detail ?? e?.message ?? e);
			exportError = msg;
			toast.error(msg);
		} finally {
			loadingPreview = false;
		}
	};

	const confirmExport = async () => {
		if (!commitMessage.trim()) {
			toast.error($i18n.t('Commit message is required'));
			return;
		}
		if (!branch.trim()) {
			toast.error($i18n.t('New branch name is required'));
			return;
		}
		exporting = true;
		try {
			const res = await startCoderExport(token, {
				owner,
				repo,
				base_branch: baseBranch,
				branch: branch.trim(),
				commit_message: commitMessage.trim(),
				changeset,
				idempotency_key: idempotencyKey
			});
			result = res;
			toast.success($i18n.t('Changes exported successfully'));
		} catch (e: any) {
			const msg = describeError(e?.detail ?? e?.message ?? e);
			exportError = msg;
			toast.error(msg);
		} finally {
			exporting = false;
		}
	};

	const close = () => {
		show = false;
		preview = null;
		result = null;
		idempotencyKey = generateUUID();
	};
</script>

<Modal bind:show containerClassName="p-3 z-9999" size="md">
	<div class="flex flex-col gap-3 max-h-[80dvh] overflow-y-auto scrollbar-thin p-1">
		{#if result}
			<div class="flex flex-col items-center gap-2 py-6 text-center">
				<div class="size-12 rounded-full bg-green-50 dark:bg-green-950/40 flex items-center justify-center">
					<svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" class="size-6 text-green-600">
						<path stroke-linecap="round" stroke-linejoin="round" d="m4.5 12.75 6 6 9-13.5" />
					</svg>
				</div>
				<div class="text-base font-medium text-black dark:text-white">{$i18n.t('Pull request created')}</div>
				{#if result.commit_sha}
					<div class="text-xs font-mono text-gray-500">commit {result.commit_sha.slice(0, 10)}</div>
				{/if}
				{#if result.pr_url}
					<a
						href={result.pr_url}
						target="_blank"
						rel="noopener noreferrer"
						class="text-sm text-blue-500 hover:underline"
					>
						PR #{result.pr_number} →
					</a>
				{/if}
				<button
					type="button"
					class="mt-2 px-3.5 py-1.5 rounded-xl text-sm bg-gray-100 dark:bg-gray-800 hover:bg-gray-200 dark:hover:bg-gray-700"
					on:click={close}>{$i18n.t('Close')}</button
				>
			</div>
		{:else}
			<div class="flex items-center justify-between">
				<div class="font-semibold text-black dark:text-white">
					{$i18n.t('Export to GitHub')}
				</div>
				<div class="text-xs text-gray-500">{owner}/{repo} ← {baseBranch}</div>
			</div>

			<div class="flex flex-col gap-2">
				<label class="text-xs font-medium text-gray-600 dark:text-gray-400" for="coder-branch">
					{$i18n.t('New branch name')}
				</label>
				<input
					id="coder-branch"
					bind:value={branch}
					class="rounded-xl bg-gray-50 dark:bg-gray-850 px-3 py-2 text-sm font-mono outline-hidden ring-1 ring-transparent focus:ring-gray-300 dark:focus:ring-gray-700"
				/>
			</div>

			<div class="flex flex-col gap-2">
				<label class="text-xs font-medium text-gray-600 dark:text-gray-400" for="coder-commit">
					{$i18n.t('Commit message')}
				</label>
				<textarea
					id="coder-commit"
					bind:value={commitMessage}
					rows="2"
					class="rounded-xl bg-gray-50 dark:bg-gray-850 px-3 py-2 text-sm outline-hidden ring-1 ring-transparent focus:ring-gray-300 dark:focus:ring-gray-700 resize-none"
				></textarea>
			</div>

			<div class="text-[11px] text-gray-500 flex items-center gap-1.5">
				<svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" class="size-3.5 shrink-0">
					<path
						stroke-linecap="round"
						stroke-linejoin="round"
						d="M12 9v3.75m9-.75a9 9 0 1 1-18 0 9 9 0 0 1 18 0Zm-9 3.75h.008v.008H12v-.008Z"
					/>
				</svg>
				{$i18n.t('Pull request is created automatically for every export.')}
			</div>

			{#if preview}
				<div class="flex flex-col gap-2">
					{#each preview.errors as err (err.path + err.code)}
						<div class="text-xs rounded-xl bg-red-50 dark:bg-red-950/30 text-red-600 dark:text-red-400 px-3 py-2">
							<span class="font-mono">{err.path}</span>: {err.message}
						</div>
					{/each}
					{#each preview.diffs as d (d.path)}
						<div class="flex flex-col gap-1">
							<div class="text-xs font-mono text-gray-600 dark:text-gray-400 flex items-center gap-1.5">
								<span
									class="px-1.5 py-0.5 rounded text-[10px] font-sans {d.action === 'create'
										? 'bg-green-100 text-green-700 dark:bg-green-950/50 dark:text-green-400'
										: d.action === 'delete'
											? 'bg-red-100 text-red-700 dark:bg-red-950/50 dark:text-red-400'
											: 'bg-blue-100 text-blue-700 dark:bg-blue-950/50 dark:text-blue-400'}"
								>{d.action}</span>
								{d.path}
							</div>
							<DiffView diff={d.diff} action={d.action} />
						</div>
					{/each}
				</div>
			{/if}

			{#if exportError}
				<div class="text-xs rounded-xl bg-red-50 dark:bg-red-950/30 text-red-600 dark:text-red-400 px-3 py-2">
					{exportError}
				</div>
			{/if}

			<div class="flex justify-end gap-2 pt-1">
				<button
					type="button"
					class="px-3.5 py-1.5 rounded-xl text-sm bg-gray-100 dark:bg-gray-800 hover:bg-gray-200 dark:hover:bg-gray-700 disabled:opacity-50"
					disabled={loadingPreview || changeset.files.length === 0}
					on:click={runPreview}>
					{#if loadingPreview}
						<Spinner className="size-4" />
					{:else}
						{$i18n.t('Preview changes')}
					{/if}
				</button>
				<button
					type="button"
					class="px-3.5 py-1.5 rounded-xl text-sm bg-gray-900 text-white dark:bg-white dark:text-gray-900 hover:bg-gray-800 disabled:opacity-50 flex items-center gap-2"
					disabled={exporting || !preview?.valid}
					on:click={confirmExport}>
					{#if exporting}
						<Spinner className="size-4" />
					{/if}
					{$i18n.t('Export to GitHub')}
				</button>
			</div>
		{/if}
	</div>
</Modal>
