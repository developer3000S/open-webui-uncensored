<script lang="ts">
	import { toast } from 'svelte-sonner';

	import { tick, getContext, onMount, createEventDispatcher } from 'svelte';
	const dispatch = createEventDispatcher();
	import type { Writable } from 'svelte/store';
	
	import { settings } from '$lib/stores';
	import { copyToClipboard } from '$lib/utils';

	import MultiResponseMessages from './MultiResponseMessages.svelte';
	import ResponseMessage from './ResponseMessage.svelte';
	import UserMessage from './UserMessage.svelte';

	export let chatId: any;
	export let selectedModels: any = [];
	export let idx: any = 0;
	export let history: { messages?: Record<string, any>; currentId?: string | null; [key: string]: any } = {};
	export let messageId: any;
	export let user: any;
	export let setInputText: Function = () => {};
	export let gotoMessage: any;
	export let showPreviousMessage: any;
	export let showNextMessage: any;
	export let updateChat: any;
	export let editMessage: any;
	export let saveMessage: any;
	export let deleteMessage: any;
	export let rateMessage: any;
	export let actionMessage: any;
	export let submitMessage: any;
	export let regenerateResponse: any;
	export let continueResponse: any;
	export let mergeResponses: any;
	export let addMessages: any;
	export let triggerScroll: any;
	export let readOnly: any = false;
	export let editCodeBlock: any = true;
	export let topPadding: any = false;
</script>

<div
	role="listitem"
	class="flex flex-col justify-between px-5 mb-3 w-full {($settings?.widescreenMode ?? null)
		? 'max-w-full'
		: 'max-w-5xl'} mx-auto rounded-lg group message-listitem"
>
	{#if history.messages[messageId]}
		{#if history.messages[messageId].role === 'user'}
			<UserMessage
				{user}
				{chatId}
				{history}
				{messageId}
				isFirstMessage={idx === 0}
				siblings={history.messages[messageId].parentId !== null
					? (history.messages[history.messages[messageId].parentId]?.childrenIds ?? [])
					: (Object.values(history.messages)
							.filter((message) => message.parentId === null)
							.map((message) => message.id) ?? [])}
				{gotoMessage}
				{showPreviousMessage}
				{showNextMessage}
				{editMessage}
				{deleteMessage}
				{readOnly}
				{editCodeBlock}
				{topPadding}
			/>
		{:else if (history.messages[history.messages[messageId].parentId]?.models?.length ?? 1) === 1}
			<ResponseMessage
				{chatId}
				{history}
				{messageId}
				{selectedModels}
				isLastMessage={messageId === history.currentId}
				siblings={history.messages[history.messages[messageId].parentId]?.childrenIds ?? []}
				{setInputText}
				{gotoMessage}
				{showPreviousMessage}
				{showNextMessage}
				{updateChat}
				{editMessage}
				{saveMessage}
				{rateMessage}
				{actionMessage}
				{submitMessage}
				{deleteMessage}
				{continueResponse}
				{regenerateResponse}
				{addMessages}
				{readOnly}
				{editCodeBlock}
				{topPadding}
			/>
		{:else}
			{#key messageId}
				<MultiResponseMessages
					bind:history
					{chatId}
					{messageId}
					{selectedModels}
					isLastMessage={messageId === history?.currentId}
					{setInputText}
					{updateChat}
					{editMessage}
					{saveMessage}
					{rateMessage}
					{actionMessage}
					{submitMessage}
					{deleteMessage}
					{continueResponse}
					{regenerateResponse}
					{mergeResponses}
					{triggerScroll}
					{addMessages}
					{readOnly}
					{editCodeBlock}
					{topPadding}
				/>
			{/key}
		{/if}
	{/if}
</div>

<style>
	/* Browser-native virtualization: skip rendering of off-screen messages
	   without destroying their component trees. Replaces the JS-based
	   culling that caused catastrophic mount/destroy thrashing. */
	.message-listitem {
		content-visibility: auto;
		contain-intrinsic-size: auto 150px;
	}
</style>
