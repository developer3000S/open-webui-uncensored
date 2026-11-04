<script lang="ts">
	import type { i18n as i18nType } from 'i18next';
	import { getContext } from 'svelte';
	const i18n = getContext<Writable<i18nType>>('i18n');

	import type { Writable } from 'svelte/store';

	import Modal from '$lib/components/common/Modal.svelte';
	import AccessControl from './AccessControl.svelte';
	import XMark from '$lib/components/icons/XMark.svelte';

	type AccessGrant = {
		id?: string;
		principal_type: 'user' | 'group';
		principal_id: string;
		permission: 'read' | 'write';
	};

	export let show: any = false;
	export let accessGrants: AccessGrant[] = [];
	export let accessControl: any = undefined;
	export let accessRoles = ['read'];

	export let share: any = true;
	export let sharePublic: any = true;
	export let shareUsers: any = true;
	export let onChange: any = () => {};
</script>

<Modal size="sm" bind:show>
	<div>
		<div class=" flex justify-between dark:text-gray-100 px-5 pt-3 pb-1">
			<div class=" text-lg font-medium self-center font-primary">
				{$i18n.t('Access Control')}
			</div>
			<button
				class="self-center"
				on:click={() => {
					show = false;
				}}
			>
				<XMark className={'size-5'} />
			</button>
		</div>

		<div class="w-full px-5 pb-4 dark:text-white">
			<AccessControl
				bind:accessGrants
				bind:accessControl
				{onChange}
				{accessRoles}
				{share}
				{sharePublic}
				{shareUsers}
			/>
		</div>
	</div>
</Modal>

<Modal size="sm" bind:show>
	<div>
		<div class=" flex justify-between dark:text-gray-100 px-5 pt-3 pb-1">
			<div class=" text-lg font-medium self-center font-primary">
				{$i18n.t('Access Control')}
			</div>
			<button
				class="self-center"
				on:click={() => {
					show = false;
				}}
			>
				<XMark className={'size-5'} />
			</button>
		</div>

		<div class="w-full px-5 pb-4 dark:text-white">
			<AccessControl
				bind:accessGrants
				bind:accessControl
				{onChange}
				{accessRoles}
				{share}
				{sharePublic}
				{shareUsers}
			/>
		</div>
	</div>
</Modal>
