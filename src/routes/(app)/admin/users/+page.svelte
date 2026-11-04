<script>
	import { goto } from '$app/navigation';
	import { onMount } from 'svelte';

	// @ts-ignore
	onMount(async () => {
		await goto('/admin/users/overview');
	});
</script>
