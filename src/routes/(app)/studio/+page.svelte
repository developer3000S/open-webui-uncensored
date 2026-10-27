<script lang="ts">
	import { onMount, onDestroy } from 'svelte';
	import { page } from '$app/stores';
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

	let tab: StudioTab | null = null;
	$: {
		const t = $page.url.searchParams.get('tab');
		tab = (STUDIO_TABS as readonly string[]).includes(t ?? '') ? (t as StudioTab) : null;
	}

	let iframeEl: HTMLIFrameElement | null = null;

	// Trailing slash is required: '/studio' (no slash) is not matched by the
	// studio_spa_proxy route and falls through to the OWUI SPA mount.
	const studioUrl = '/studio/';

	const requestTabSwitch = () => {
		if (!iframeEl?.contentWindow || !tab) return;
		iframeEl.contentWindow.postMessage({ type: 'studio:tab', tab }, location.origin);
	};

	// The iframe loads once and is never reloaded on navigation, so a sidebar
	// click only changes `tab` — the switch must be pushed to the iframe here.
	$: if (iframeEl && tab) {
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
