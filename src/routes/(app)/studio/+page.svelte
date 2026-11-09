<script lang="ts">
	import { onMount, onDestroy } from 'svelte';
	import { page } from '$app/state';
	import { showSidebar } from '$lib/stores';

	// Studio tabs (App.jsx activeTab values) that can be opened via /studio?tab=<name>
	const STUDIO_TABS = [
		'generator',
		'chat',
		'agents',
		'speech',
		'tts',
		'models',
		'settings'
	] as const;

	type StudioTab = (typeof STUDIO_TABS)[number];

	let tab: StudioTab = 'generator'; // default tab if none specified
	let prevTab: StudioTab | null = null;

	$: {
		const t = page?.url?.searchParams?.get('tab') as StudioTab | undefined;
		const next = STUDIO_TABS.includes(t ?? 'generator') ? (t ?? 'generator') : 'generator';
		if (next !== tab) {
			tab = next;
		}
	}

	let iframeEl: HTMLIFrameElement | null = null;

	// Trailing slash is required: '/studio' (no slash) is not matched by the
	// studio_spa_proxy route and falls through to the OWUI SPA mount.
	const studioUrl = '/studio/';

	const requestTabSwitch = (targetTab?: StudioTab) => {
		const t = targetTab ?? tab;
		if (!iframeEl?.contentWindow || !t) return;
		try {
			iframeEl.contentWindow.postMessage({ type: 'studio:tab', tab: t }, location.origin);
		} catch (e) {
			console.error('Failed to post studio tab switch message:', e);
		}
	};

	// Push tab changes to the iframe React app via postMessage
	$: if (iframeEl && tab && tab !== prevTab) {
		prevTab = tab;
		requestTabSwitch();
	}

	const onIframeLoad = () => {
		requestTabSwitch();
		// Re-send after the React app hydrates (it ignores messages before mount)
		setTimeout(requestTabSwitch, 600);
	};

	const onMessage = (e: MessageEvent) => {
		if (e.origin !== location.origin) return;
		if (e.data?.type === 'studio:ready') {
			requestTabSwitch();
		}
	};

	onMount(() => window.addEventListener('message', onMessage));
	onDestroy(() => window.removeEventListener('message', onMessage));
</script>

<div
	class="flex flex-col w-full h-full overflow-hidden {$showSidebar
		? 'md:max-w-[calc(100%-var(--sidebar-width))]'
		: ''}"
>
	<iframe
		bind:this={iframeEl}
		src={studioUrl}
		title="Uncensored AI Studio"
		class="w-full h-full flex-1 border-0"
		on:load={onIframeLoad}
	></iframe>
</div>
