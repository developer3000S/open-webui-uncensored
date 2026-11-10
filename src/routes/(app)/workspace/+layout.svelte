<script lang="ts">
	import { onMount } from 'svelte';
	import { goto } from '$app/navigation';
	import { user } from '$lib/stores';
	import i18n from '$lib/i18n';
	import { WEBUI_NAME } from '$lib/stores';

	let loaded = false;

	// @ts-ignore
	onMount(async () => {
		if ($user?.role !== 'admin') {
			if (window.location.pathname.includes('/models') && !$user?.permissions?.workspace?.models) {
				goto('/');
			} else if (
				window.location.pathname.includes('/knowledge') &&
				!$user?.permissions?.workspace?.knowledge
			) {
				goto('/');
			} else if (
				window.location.pathname.includes('/prompts') &&
				!$user?.permissions?.workspace?.prompts
			) {
				goto('/');
			} else if (
				window.location.pathname.includes('/tools') &&
				!$user?.permissions?.workspace?.tools
			) {
				goto('/');
			} else if (
				window.location.pathname.includes('/skills') &&
				!$user?.permissions?.workspace?.skills
			) {
				goto('/');
			}
		}

		loaded = true;
	});

	const workspaceTabs = [
		{ id: 'knowledge', label: 'Knowledge', href: '/workspace/knowledge' },
		{ id: 'models', label: 'Models', href: '/workspace/models' },
		{ id: 'prompts', label: 'Prompts', href: '/workspace/prompts' },
		{ id: 'skills', label: 'Skills', href: '/workspace/skills' },
		{ id: 'tools', label: 'Tools', href: '/workspace/tools' }
	];

	const isActive = (href: string) => {
		if (typeof window === 'undefined') return false;
		return window.location.pathname.startsWith(href);
	};
</script>

<svelte:head>
	<title>
		{$i18n.t('Workspace')} • {$WEBUI_NAME}
	</title>
</svelte:head>

{#if loaded}
	<div class="flex flex-col h-screen">
		<!-- Horizontal workspace submenu -->
		<nav class="flex flex-shrink-0 items-center gap-1 px-3 py-2 border-b border-gray-200 dark:border-gray-800 bg-gray-50 dark:bg-gray-900/50 z-10 overflow-x-auto scrollbar-none">
			{#each workspaceTabs as tab}
				<a
					href={tab.href}
					class="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm font-medium transition whitespace-nowrap min-w-fit
					{isActive(tab.href)
						? 'bg-blue-600 dark:bg-blue-500 text-white shadow-sm'
						: 'text-gray-600 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-800'}"
					aria-current={isActive(tab.href) ? 'page' : null}
				>
					<svg
						xmlns="http://www.w3.org/2000/svg"
						class="h-4 w-4"
						viewBox="0 0 20 20"
						fill="currentColor"
					>
						{#if tab.id === 'knowledge'}
							<path
								fill-rule="evenodd"
								d="M18 10a8 8 0 11-16 0 8 8 0 0116 0zm-7-4a1 1 0 11-2 0 1 1 0 012 0zM9 9a1 1 0 000 2h2a1 1 0 100-2H9z"
								clip-rule="evenodd"
							/>
						{:else if tab.id === 'models'}
							<path
								fill-rule="evenodd"
								d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-8.707l-3-3a1 1 0 00-1.414 1.414L10.586 9H7a1 1 0 100 2h3.586l-1.293 1.293a1 1 0 101.414 1.414l3-3a1 1 0 000-1.414z"
								clip-rule="evenodd"
							/>
						{:else if tab.id === 'prompts'}
							<path
								fill-rule="evenodd"
								d="M10 18a8 8 0 100-16 8 8 0 000 16zM9.555 7.168A1 1 0 008 8v4a1 1 0 001.555.832l3-2a1 1 0 000-1.664l-3-2z"
								clip-rule="evenodd"
							/>
						{:else if tab.id === 'skills'}
							<path
								fill-rule="evenodd"
								d="M10 18a8 8 0 100-16 8 8 0 000 16zm-1-13a1 1 0 10-2 0v.092a7.57 7.57 0 001.415.839l.378.378a1 1 0 001.414-1.414l-.378-.378A7.57 7.57 0 0010 5.908V5zm-5 5a1 1 0 100-2 1 1 0 000 2z"
								clip-rule="evenodd"
							/>
						{:else if tab.id === 'tools'}
							<path
								fill-rule="evenodd"
								d="M10 2a1 1 0 011 1v1a1 1 0 11-2 0V3a1 1 0 011-1zm4 8a4 4 0 11-8 0 4 4 0 018 0zm-.464 4.95l.707.707a1 1 0 001.414-1.414l-.707-.707a1 1 0 00-1.414 1.414zm2.12-10.607a1 1 0 010 1.414l-.706.707a1 1 0 11-1.414-1.414l.707-.707a1 1 0 011.414 0zM10 18a8 8 0 100-16 8 8 0 000 16zm1-13a1 1 0 10-2 0v.092a7.57 7.57 0 001.415.839l.378.378a1 1 0 001.414-1.414l-.378-.378A7.57 7.57 0 0011 5.908V5zm5 5a1 1 0 100-2 1 1 0 000 2z"
								clip-rule="evenodd"
							/>
						{/if}
					</svg>
					<span>{tab.label}</span>
				</a>
			{/each}
		</nav>

		<!-- Main content -->
		<div class="flex-1 overflow-auto bg-white dark:bg-gray-900">
			<slot />
		</div>
	</div>
{/if}
