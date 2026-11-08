<script lang="ts">
	import type { i18n as i18nType } from 'i18next';
	import { getContext, onMount } from 'svelte';
	const i18n = getContext<Writable<i18nType>>('i18n');

	import type { Writable } from 'svelte/store';

	import ManageOllama from './ManageOllama.svelte';

	export let ollamaConfig: any = null;

	let selectedUrlIdx = 0;
</script>

{#if ollamaConfig}
	<div class="flex-1 mb-2.5 pr-1.5 rounded-lg bg-gray-50 dark:text-gray-300 dark:bg-gray-850">
		<select
			class="w-full py-2 px-4 text-sm outline-hidden bg-transparent"
			bind:value={selectedUrlIdx}
			placeholder={$i18n.t('Select an Ollama instance')}
		>
			{#each ollamaConfig.OLLAMA_BASE_URLS as url, idx}
				<option value={idx}>{url}</option>
			{/each}
		</select>
	</div>

	<div>
		<ManageOllama urlIdx={selectedUrlIdx} />
	</div>
{/if}
