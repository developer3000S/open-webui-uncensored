<script lang="ts">
	import { getContext, createEventDispatcher, onDestroy } from 'svelte';
	import { useSvelteFlow, useNodesInitialized, useStore, SvelteFlowProvider } from '@xyflow/svelte';

	const dispatch = createEventDispatcher();

	import View from './Overview/View.svelte';

	export let history: {
		messages?: Record<string, any>;
		currentId?: string | null;
		[key: string]: any;
	} = {};
	export let onClose: any;
	export let onNodeClick: any;
</script>

<SvelteFlowProvider>
	<View {history} {onClose} {onNodeClick} />
</SvelteFlowProvider>
