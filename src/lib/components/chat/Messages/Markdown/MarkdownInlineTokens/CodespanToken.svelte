<script lang="ts">
	import type { i18n as i18nType } from 'i18next';
	import { getContext } from 'svelte';
	const i18n = getContext<Writable<i18nType>>('i18n');

	import { copyToClipboard, unescapeHtml } from '$lib/utils';
	import { toast } from 'svelte-sonner';

	import type { Writable } from 'svelte/store';

	export let token: any;
	export let done: any = true;
</script>

<!-- svelte-ignore a11y-click-events-have-key-events -->
<!-- svelte-ignore a11y-no-noninteractive-element-interactions -->
<code
	class="codespan cursor-pointer {!done ? 'fade-in-token' : ''}"
	on:click={() => {
		copyToClipboard(unescapeHtml(token.text));
		toast.success($i18n.t('Copied to clipboard'));
	}}>{unescapeHtml(token.text)}</code
>
