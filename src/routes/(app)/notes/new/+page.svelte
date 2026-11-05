<script lang="ts">
	import { onMount } from 'svelte';

	import { goto } from '$app/navigation';
	import { page } from '$app/stores';

	import dayjs from '$lib/dayjs';
	import { createNoteHandler } from '$lib/components/notes/utils';

	// @ts-ignore
	onMount(async () => {
		const title = new URLSearchParams(window.location.search).get('title') ?? dayjs().format('YYYY-MM-DD');
		const content = new URLSearchParams(window.location.search).get('content') ?? '';

		const res = await createNoteHandler(title, content);

		if (res) {
			goto(`/notes/${res.id}`);
		}
	});
</script>
