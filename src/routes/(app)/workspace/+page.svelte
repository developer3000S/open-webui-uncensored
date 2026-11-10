<script lang="ts">
	import { goto } from '$app/navigation';
	import { user } from '$lib/stores';
	import { onMount } from 'svelte';

	onMount(() => {
		const workspace = $user?.permissions?.workspace;

		// Admins always have access to Workspace (sidebar shows it for admins regardless of permissions).
		if ($user?.role === 'admin') {
			goto('/workspace/knowledge');
		} else if (workspace?.knowledge) {
			goto('/workspace/knowledge');
		} else if (workspace?.models) {
			goto('/workspace/models');
		} else if (workspace?.prompts) {
			goto('/workspace/prompts');
		} else if (workspace?.tools) {
			goto('/workspace/tools');
		} else if (workspace?.skills) {
			goto('/workspace/skills');
		} else {
			goto('/');
		}
	});
</script>
