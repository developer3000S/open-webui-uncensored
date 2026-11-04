<script lang="ts">
	import type { i18n as i18nType } from 'i18next';
	import { getContext } from 'svelte';
	const i18n = getContext<Writable<i18nType>>('i18n');

	export let diff: any = '';
	export let action: string;

	import type { Writable } from 'svelte/store';

	const isHeader = (line: string) =>
		line.startsWith('@@') ||
		line.startsWith('diff ') ||
		line.startsWith('index ') ||
		line.startsWith('--- ') ||
		line.startsWith('+++ ');

	const lineClass = (line: string) => {
		if (isHeader(line)) return 'text-gray-400 bg-gray-50 dark:bg-gray-900';
		if (line.startsWith('+'))
			return 'bg-green-50 dark:bg-green-950/40 text-green-800 dark:text-green-300';
		if (line.startsWith('-')) return 'bg-red-50 dark:bg-red-950/40 text-red-800 dark:text-red-300';
		return 'text-gray-600 dark:text-gray-400';
	};
</script>

<div
	class="rounded-xl overflow-hidden border border-gray-200 dark:border-gray-700 font-mono text-[11px] leading-relaxed"
>
	{#if action === 'delete'}
		<div
			class="px-2.5 py-1 bg-red-50 dark:bg-red-950/40 text-red-600 dark:text-red-400 border-b border-gray-200 dark:border-gray-700"
		>
			{$i18n.t('This file will be deleted')}
		</div>
	{:else if action === 'create'}
		<div
			class="px-2.5 py-1 bg-green-50 dark:bg-green-950/40 text-green-700 dark:text-green-400 border-b border-gray-200 dark:border-gray-700"
		>
			{$i18n.t('New file')}
		</div>
	{/if}
	<div class="overflow-x-auto py-1">
		{#each diff.split('\n') as line}
			<div class="px-2.5 whitespace-pre {lineClass(line)}">{line}</div>
		{/each}
	</div>
</div>

<div
	class="rounded-xl overflow-hidden border border-gray-200 dark:border-gray-700 font-mono text-[11px] leading-relaxed"
>
	{#if action === 'delete'}
		<div
			class="px-2.5 py-1 bg-red-50 dark:bg-red-950/40 text-red-600 dark:text-red-400 border-b border-gray-200 dark:border-gray-700"
		>
			{$i18n.t('This file will be deleted')}
		</div>
	{:else if action === 'create'}
		<div
			class="px-2.5 py-1 bg-green-50 dark:bg-green-950/40 text-green-700 dark:text-green-400 border-b border-gray-200 dark:border-gray-700"
		>
			{$i18n.t('New file')}
		</div>
	{/if}
	<div class="overflow-x-auto py-1">
		{#each diff.split('\n') as line}
			<div class="px-2.5 whitespace-pre {lineClass(line)}">{line}</div>
		{/each}
	</div>
</div>
