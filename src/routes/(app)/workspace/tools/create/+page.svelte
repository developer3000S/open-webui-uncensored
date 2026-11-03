<script lang="ts">
	import type i18nType from 'i18next';
	import { getContext, onMount } from 'svelte';
	const i18n = getContext<i18nType>('i18n');

	import { goto } from '$app/navigation';
	import { createNewTool, getTools } from '$lib/apis/tools';
	import ToolkitEditor from '$lib/components/workspace/Tools/ToolkitEditor.svelte';
	import { WEBUI_VERSION } from '$lib/constants';
	import { tools } from '$lib/stores';
	import { compareVersion, extractFrontmatter } from '$lib/utils';
	import { toast } from 'svelte-sonner';

	import type { Writable } from 'svelte/store';

	let mounted = false;
	let clone = false;
	let tool: any = null;

	const saveHandler = async (data: any) => {
		console.log(data);

		const manifest = extractFrontmatter(data.content);
		if (compareVersion(manifest?.required_open_webui_version ?? '0.0.0', WEBUI_VERSION)) {
			console.log('Version is lower than required');
			toast.error(
				i18n.t(
					'Open WebUI version (v{{OPEN_WEBUI_VERSION}}) is lower than required version (v{{REQUIRED_VERSION}})',
					{
						OPEN_WEBUI_VERSION: WEBUI_VERSION,
						REQUIRED_VERSION: manifest?.required_open_webui_version ?? '0.0.0'
					}
				)
			);
			return;
		}

		const res = await createNewTool(localStorage.token, {
			id: data.id,
			name: data.name,
			meta: data.meta,
			content: data.content,
			access_grants: data.access_grants
		}).catch(async (error)=> {
			toast.error(`${error}`);
			return null;
		});

		if (res) {
			toast.success(i18n.t('Tool created successfully'));
			tools.set(await getTools(localStorage.token));

			await goto('/workspace/tools');
		}
	};

	onMount(() => {
		window.addEventListener('message', async (event: any) => {
			if (
				!['https://openwebui.com', 'https://www.openwebui.com', 'http://localhost:9999'].includes(
					event.origin
				)
			)
				return;

			tool = JSON.parse(event.data);
			console.log(tool);
		});

		if (window.opener ?? false) {
			window.opener.postMessage('loaded', '*');
		}

		if (sessionStorage.tool) {
			tool = JSON.parse(sessionStorage.tool);
			sessionStorage.removeItem('tool');

			console.log(tool);
			clone = true;
		}

		mounted = true;
	});
</script>

{#if mounted}
	{#key tool?.content}
		<ToolkitEditor
			id={tool?.id ?? ''}
			name={tool?.name ?? ''}
			meta={tool?.meta ?? { description: '' }}
			content={tool?.content ?? ''}
			accessGrants={tool?.access_grants !== undefined ? tool.access_grants : []}
			{clone}
			onSave={(value: any) => {
				saveHandler(value);
			}}
		/>
	{/key}
{/if}

{#if mounted}
	{#key tool?.content}
		<ToolkitEditor
			id={tool?.id ?? ''}
			name={tool?.name ?? ''}
			meta={tool?.meta ?? { description: '' }}
			content={tool?.content ?? ''}
			accessGrants={tool?.access_grants !== undefined ? tool.access_grants : []}
			{clone}
			onSave={(value: any) => {
				saveHandler(value);
			}}
		/>
	{/key}
{/if}
