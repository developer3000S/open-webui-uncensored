<script lang="ts">
	import { v4 as uuidv4 } from 'uuid';
	import {
		chats,
		config,
		settings,
		user as _user,
		mobile,
		currentChatPage,
		temporaryChatEnabled
	} from '$lib/stores';
	import { tick, getContext, onMount, onDestroy, createEventDispatcher } from 'svelte';
	const dispatch = createEventDispatcher();

	import { toast } from 'svelte-sonner';
	import { deleteChatMessageById, getChatList, updateChatById } from '$lib/apis/chats';
	import { copyToClipboard, extractCurlyBraceWords } from '$lib/utils';

	import Message from './Messages/Message.svelte';
	import Loader from '../common/Loader.svelte';
	import Spinner from '../common/Spinner.svelte';

	import ChatPlaceholder from './ChatPlaceholder.svelte';

	const i18n = getContext<{ t: (key: string, options?: any) => string }>('i18n');

	export let className = 'h-full flex pt-8';

	export let chatId = '';
	export let user = $_user;

	export let history = {};
	export let selectedModels;
	export let atSelectedModel;

	let messages: any[] = [];

	export let setInputText: Function = () => {};

	export let sendMessage: Function;
	export let continueResponse: Function;
	export let regenerateResponse: Function;
	export let mergeResponses: Function;

	export let chatActionHandler: Function;
	export let submitMessage: Function = () => {};
	export let addMessages: Function = () => {};

	export let readOnly = false;
	export let editCodeBlock = true;

	export let topPadding = false;
	export let bottomPadding = false;
	export let autoScroll: boolean = true;

	export let onSelect = (e) => {};

	export let messagesCount: number | null = 8;
	let messagesLoading = false;

	let lastCurrentId: string | null = null;
	let pendingRebuild: number | null = null;

	onDestroy(() => {
		cancelAnimationFrame(pendingRebuild as number);
	});

	const loadMoreMessages = async () => {
		// scroll slightly down to disable continuous loading
		const element = document.getElementById('messages-container');
		if (element) {
			element.scrollTop = element.scrollTop + 100;
		}

		messagesLoading = true;
		messagesCount += 8;

		buildMessages();

		await tick();

		messagesLoading = false;
	};

	const buildMessages = () => {
		let _messages: any[] = [];

		let message = history.messages[history.currentId];
		const visitedMessageIds = new Set<string>();

		while (message && (messagesCount !== null ? _messages.length <= messagesCount : true)) {
			if (visitedMessageIds.has(message.id)) {
				console.warn('Circular dependency detected in message history', message.id);
				break;
			}
			visitedMessageIds.add(message.id);

			_messages.push(message);
			message = message.parentId !== null ? history.messages[message.parentId] : null;
		}

		messages = _messages.reverse();
	};

	// Throttle message list rebuilds to once per animation frame during streaming.
	// Structural changes (currentId change) always rebuild immediately.
	const handleHistoryChange = (currentId: string, _messages: any) => {
		if (!currentId) {
			messages = [];
			return;
		}

		const currentIdChanged = currentId !== lastCurrentId;
		lastCurrentId = currentId;

		if (currentIdChanged) {
			// Structural change: new chat, navigation, new message — rebuild immediately
			if (pendingRebuild) {
				cancelAnimationFrame(pendingRebuild);
			}
			pendingRebuild = null;
			buildMessages();
		} else if (_messages) {
			// Content update (streaming) — throttle to once per frame
			if (!pendingRebuild) {
				pendingRebuild = requestAnimationFrame(() => {
					buildMessages();
					pendingRebuild = null;
				});
			}
		}
	};

	$: if (history) {
		handleHistoryChange(history.currentId, null);
	}

	// ... остальная часть файла остается без изменений
</script>

<!-- Остальная часть файла -->
