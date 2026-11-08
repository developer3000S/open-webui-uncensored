<script lang="ts">
	import type { i18n as i18nType } from 'i18next';
	import { getContext } from 'svelte';
	const i18n = getContext<Writable<i18nType>>('i18n');

	import Dropdown from '$lib/components/common/Dropdown.svelte';
	import Sparkles from '../icons/Sparkles.svelte';
	import ChatBubbleOval from '../icons/ChatBubbleOval.svelte';

	import type { Writable } from 'svelte/store';

	export let show: any = false;
	export let onEdit: any = () => {};
	export let onChat: any = () => {};

	export let onChange: any = () => {};
</script>

<Dropdown
	bind:show
	align="end"
	sideOffset={8}
	onOpenChange={(state) => {
		onChange(state);
	}}
>
	<slot />

	<div slot="content">
		<div
			class="min-w-[170px] text-sm rounded-xl p-1 z-50 bg-white dark:bg-gray-850 dark:text-white shadow-lg font-primary"
		>
			<button
				class="flex rounded-md py-1.5 px-3 w-full hover:bg-gray-50 dark:hover:bg-gray-800 transition"
				on:click={async () => {
					onEdit();
					show = false;
				}}
			>
				<div class=" self-center mr-2">
					<Sparkles className="size-4" strokeWidth="2" />
				</div>
				<div class=" self-center truncate">{$i18n.t('Enhance')}</div>
			</button>

			<button
				class="flex rounded-md py-1.5 px-3 w-full hover:bg-gray-50 dark:hover:bg-gray-800 transition"
				on:click={() => {
					onChat();
					show = false;
				}}
			>
				<div class=" self-center mr-2">
					<ChatBubbleOval className="size-4" strokeWidth="2" />
				</div>
				<div class=" self-center truncate">{$i18n.t('Chat')}</div>
			</button>
		</div>
	</div>
</Dropdown>
