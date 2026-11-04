<script lang="ts">
	import { toast } from 'svelte-sonner';
	import { goto } from '$app/navigation';
	import { onMount, getContext } from 'svelte';

	import { page } from '$app/stores';
	import { user, showSidebar, config } from '$lib/stores';
	import { getAutomationById } from '$lib/apis/automations';

	import AutomationEditor from '$lib/components/automations/AutomationEditor.svelte';
	import Spinner from '$lib/components/common/Spinner.svelte';

	import type { Writable } from 'svelte/store';

	let automation: any = null;
	let loaded = false;

	$: automationId = $page.params.id;

	// @ts-ignore
	onMount(async () => {
		if (
			!$config?.features?.enable_automations ||
			($user?.role !== 'admin' && !($user?.permissions?.features?.automations ?? false))
		) {
			goto('/');
			return;
		}

		if (automationId) {
			const res = await getAutomationById(localStorage.token, automationId).catch((error) => {
				toast.error(`${error}`);
				return null;
			});

			if (res) {
				automation = res;
				loaded = true;
			} else {
				goto('/automations');
			}
		} else {
			goto('/automations');
		}
	});
</script>

{#if loaded && automation}
	<AutomationEditor {automation} />
{:else}
	<div
		class="w-full h-screen max-h-[100dvh] flex justify-center items-center transition-width duration-200 ease-in-out {$showSidebar
			? 'md:max-w-[calc(100%-var(--sidebar-width))]'
			: ''}"
	>
		<Spinner className="size-5" />
	</div>
{/if}
