<script lang="ts">
	import { getContext, onMount, onDestroy, createEventDispatcher } from 'svelte';

	import { toast } from 'svelte-sonner';

	import {
		listCoderRepos,
		listCoderBranches,
		listCoderOrganizations,
		getCoderTree,
		getCoderFile,
		type CoderRepo,
		type CoderBranch,
		type CoderTreeEntry
	} from '$lib/apis/coder';

	const i18n = getContext('i18n');
	const dispatch = createEventDispatcher();

	export let token: string;
	export let owner = '';
	export let repo = '';
	export let branch = '';

	let repos: CoderRepo[] = [];
	let branches: CoderBranch[] = [];
	let tree: CoderTreeEntry[] = []; let repoKey = '';

	let repoQuery = '';
	let repoSearchTimer: ReturnType<typeof setTimeout>;
	let loadingRepos = false;
	let loadingBranches = false;
	let loadingTree = false;

	// §D: organization filter for the repository list
	let orgs: { login: string }[] = [];
	let selectedOrg = '';

	let selectedPath = '';
	let fileContent: string | null = null;
	let fileBinary = false;
	let loadingFile = false;

	// collapsible tree state
	let collapsed: Record<string, boolean> = {};

	const searchRepos = async () => {
		loadingRepos = true;
		try {
			const res = await listCoderRepos(token, repoQuery || undefined, selectedOrg || undefined);
			repos = res.repos ?? [];
		} catch (e: any) {
			toast.error(e?.message ?? 'Failed to load repositories');
		} finally {
			loadingRepos = false;
		}
	};

	const loadOrgs = async () => {
		try {
			const res = await listCoderOrganizations(token);
			orgs = res.organizations ?? [];
		} catch {
			orgs = []; // non-fatal: the org filter simply stays empty
		}
	};

	const handleRepoQueryInput = () => {
		clearTimeout(repoSearchTimer);
		repoSearchTimer = setTimeout(searchRepos, 400);
	};

	const loadBranches = async () => {
		loadingBranches = true;
		branches = [];
		tree = [];
		try {
			const res = await listCoderBranches(token, owner, repo);
			branches = res.branches ?? [];
			if (!branch || !branches.some((b) => b.name === branch)) {
				const def = repos.find((r) => r.full_name === `${owner}/${repo}`)?.default_branch;
				branch = def && branches.some((b) => b.name === def) ? def : (branches[0]?.name ?? '');
			}
			if (branch) await loadTree();
		} catch (e: any) {
			toast.error(e?.message ?? 'Failed to load branches');
		} finally {
			loadingBranches = false;
		}
	};

	const loadTree = async () => {
		loadingTree = true;
		try {
			const res = await getCoderTree(token, owner, repo, branch);
			tree = res.tree ?? [];
		} catch (e: any) {
			toast.error(e?.message ?? 'Failed to load file tree');
			tree = [];
		} finally {
			loadingTree = false;
		}
	};

	const openFile = async (entry: CoderTreeEntry) => {
		if (entry.type !== 'blob') {
			collapsed[entry.path] = !collapsed[entry.path];
			return;
		}
		selectedPath = entry.path;
		loadingFile = true;
		fileContent = null;
		fileBinary = false;
		try {
			const f = await getCoderFile(token, owner, repo, entry.path, branch);
			fileBinary = f.binary;
			fileContent = f.content;
		} catch (e: any) {
			toast.error(e?.message ?? 'Failed to load file');
		} finally {
			loadingFile = false;
		}
	};

	// build a nested structure from flat tree entries
	type TreeNode = { name: string; path: string; type: 'blob' | 'tree'; children: TreeNode[]; entry?: CoderTreeEntry };

	const buildTree = (entries: CoderTreeEntry[]): TreeNode[] => {
		const root: TreeNode = { name: '', path: '', type: 'tree', children: [] };
		const map: Record<string, TreeNode> = { '': root };
		const sorted = [...entries].sort((a, b) => a.path.localeCompare(b.path));
		for (const e of sorted) {
			const parts = e.path.split('/');
			const name = parts[parts.length - 1];
			const node: TreeNode = { name, path: e.path, type: e.type, children: [], entry: e };
			const parentPath = parts.slice(0, -1).join('/');
			const parent = map[parentPath] ?? root;
			parent.children.push(node);
			map[e.path] = node;
		}
		const sortRec = (nodes: TreeNode[]) => {
			nodes.sort((a, b) => (a.type === b.type ? a.name.localeCompare(b.name) : a.type === 'tree' ? -1 : 1));
			nodes.forEach((n) => n.children.length && sortRec(n.children));
		};
		sortRec(root.children);
		return root.children;
	};

	$: nodes = buildTree(tree);

	// Reactive: load branches when owner/repo become set
	$: if (owner && repo) {
		const key = `${owner}/${repo}`;
		if (key !== repoKey) {
			repoKey = key;
			loadBranches();
		}
	}

	onMount(async () => {
		// Auto-load branches (and file tree) when the panel opens with a repo already selected
		if (owner && repo) {
			await loadBranches();
		} else {
			await searchRepos();
		}
		loadOrgs();
	});

	onDestroy(() => clearTimeout(repoSearchTimer));
</script>

<div class="flex flex-col h-full text-sm">
	<!-- Repository selector -->
	<div class="p-2.5 space-y-2 border-b border-gray-100 dark:border-gray-800">
		{#if !(owner && repo)}
			<input
				bind:value={repoQuery}
				on:input={handleRepoQueryInput}
				placeholder={$i18n.t('Search a repository')}
				class="w-full rounded-xl bg-gray-50 dark:bg-gray-850 px-3 py-1.5 text-xs outline-hidden ring-1 ring-transparent focus:ring-gray-300 dark:focus:ring-gray-700"
			/>
			{#if orgs.length > 0}
				<!-- §D: filter the repository list by organization -->
				<select
					bind:value={selectedOrg}
					on:change={searchRepos}
					class="w-full rounded-xl bg-gray-50 dark:bg-gray-850 px-2.5 py-1.5 text-xs outline-hidden"
				>
					<option value="">{$i18n.t('All organizations')}</option>
					{#each orgs as o (o.login)}
						<option value={o.login}>{o.login}</option>
					{/each}
				</select>
			{/if}
		{:else}
			<div class="flex items-center justify-between gap-1">
				<div class="font-medium truncate text-black dark:text-white">{owner}/{repo}</div>
				<button
					type="button"
					class="text-gray-500 hover:text-gray-700 dark:hover:text-gray-300 shrink-0 text-xs"
					on:click={() => {
						owner = '';
						repo = '';
						branch = '';
						repos = [];
						tree = [];
						branches = [];
						fileContent = null;
						selectedPath = '';
						searchRepos();
					}}>{$i18n.t('Change')}</button
				>
			</div>

			<select
				bind:value={branch}
				on:change={loadTree}
				class="w-full rounded-xl bg-gray-50 dark:bg-gray-850 px-2.5 py-1.5 text-xs outline-hidden"
				disabled={loadingBranches}
			>
				{#each branches as b}
					<option value={b.name}>{b.name}</option>
				{/each}
			</select>
		{/if}

		{#if !(owner && repo)}
			<div class="max-h-56 overflow-y-auto scrollbar-thin -mx-1">
				{#if loadingRepos}
					<div class="px-2 py-3 text-xs text-gray-500">...</div>
				{:else}
					{#each repos as r (r.full_name)}
						<button
							type="button"
							class="w-full text-left px-2 py-1.5 rounded-lg hover:bg-gray-50 dark:hover:bg-gray-800 flex items-center gap-2"
							on:click={() => {
								owner = r.owner;
								repo = r.name;
								branch = r.default_branch ?? '';
								loadBranches();
							}}
						>
							<span class="truncate flex-1">{r.full_name}</span>
							{#if r.private}
								<span class="text-[10px] px-1 rounded bg-gray-100 dark:bg-gray-800 text-gray-500">private</span>
							{/if}
						</button>
					{:else}
						<div class="px-2 py-3 text-xs text-gray-500">{$i18n.t('No repositories found')}</div>
					{/each}
				{/if}
			</div>
		{/if}
	</div>

	{#if owner && repo}
		<!-- File tree -->
		<div class="flex-1 overflow-y-auto scrollbar-thin p-1.5 min-h-0">
			{#if loadingTree}
				<div class="px-2 py-3 text-xs text-gray-500">...</div>
			{:else}
				{#snippet treeList(list: TreeNode[], depth: number)}
					<div class="flex flex-col">
						{#each list as node (node.path)}
							{#if !(depth > 0 && collapsed[node.path.split('/').slice(0, -1).join('/')])}
								<button
									type="button"
									class="flex items-center gap-1 w-full text-left px-1.5 py-1 rounded-md hover:bg-gray-50 dark:hover:bg-gray-800 {selectedPath ===
									node.path
										? 'bg-gray-100 dark:bg-gray-800 text-black dark:text-white'
										: 'text-gray-600 dark:text-gray-400'}"
									style="padding-left: {6 + depth * 12}px"
									on:click={() => openFile(node.entry ?? { path: node.path, type: node.type, sha: '' })}
								>
									{#if node.type === 'tree'}
										<svg
											xmlns="http://www.w3.org/2000/svg"
											fill="none"
											viewBox="0 0 24 24"
											stroke-width="2"
											stroke="currentColor"
											class="size-3 shrink-0 transition-transform {collapsed[node.path] ? '' : 'rotate-90'}"
										>
											<path stroke-linecap="round" stroke-linejoin="round" d="m8.25 4.5 7.5 7.5-7.5 7.5" />
										</svg>
									{:else}
										<span class="size-3 shrink-0"></span>
									{/if}
									<span class="truncate">{node.name}</span>
								</button>
								{#if node.type === 'tree' && !collapsed[node.path]}
									{@render treeList(node.children, depth + 1)}
								{/if}
							{/if}
						{/each}
					</div>
				{/snippet}
				{@render treeList(nodes, 0)}
			{/if}
		</div>

		<!-- Selected file preview -->
		{#if selectedPath}
			<div class="border-t border-gray-100 dark:border-gray-800 max-h-64 overflow-auto scrollbar-thin">
				<div
					class="sticky top-0 flex items-center justify-between gap-2 bg-gray-50 dark:bg-gray-900 px-2.5 py-1.5 border-b border-gray-100 dark:border-gray-800"
				>
					<div class="truncate text-xs font-mono text-gray-600 dark:text-gray-400">{selectedPath}</div>
					<div class="flex gap-1 shrink-0">
						<button
							type="button"
							class="text-[11px] px-2 py-0.5 rounded-lg bg-gray-200/60 dark:bg-gray-700/60 hover:bg-gray-200 dark:hover:bg-gray-700"
							on:click={() => {
								if (fileBinary) {
									toast.error($i18n.t('Binary files cannot be attached'));
									return;
								}
								dispatch('attach', { path: selectedPath, content: fileContent });
							}}>{$i18n.t('Attach file to context')}</button
						>
						<button
							type="button"
							class="text-[11px] px-1.5 py-0.5 rounded-lg hover:bg-gray-200/60 dark:hover:bg-gray-700/60 text-gray-500"
							on:click={() => {
								selectedPath = '';
								fileContent = null;
							}}>✕</button
						>
					</div>
				</div>
				{#if loadingFile}
					<div class="px-3 py-3 text-xs text-gray-500">...</div>
				{:else if fileBinary}
					<div class="px-3 py-3 text-xs text-gray-500">{$i18n.t('Binary file — content is not shown')}</div>
				{:else}
					<pre
						class="px-3 py-2 text-[11px] font-mono whitespace-pre text-gray-700 dark:text-gray-300 leading-relaxed">{fileContent?.slice(0, 20000)}</pre
					>
				{/if}
			</div>
		{/if}
	{/if}
</div>
