<script lang="ts">
	import { getContext, onMount } from 'svelte';
	import type { Writable } from 'svelte/store';
	import type { i18n as i18nType } from 'i18next';

	import {
		getComments,
		createComment,
		updateComment,
		deleteComment
	} from '$lib/apis/comments';

	const i18n: Writable<i18nType> = getContext<Writable<i18nType>>('i18n');

	export let objectType;
	export let objectId;
	export let parentId;
	export let messageId;

	let comments: any[] = [];
	let loading = false;
	let newCommentContent = '';
	let editingId: string | null = null;
	let editContent = '';
	let showThread = true;

	const token = localStorage.token;

	const loadComments = async () => {
		if (!token) return;
		loading = true;
		try {
			const res = await getComments(token, objectType, objectId, parentId);
			comments = res?.comments ?? [];
		} catch (e) {
			console.error('Failed to load comments', e);
		} finally {
			loading = false;
		}
	};

	const addComment = async () => {
		if (!token || !newCommentContent.trim()) return;

		try {
			const res = await createComment(
				token,
				objectType,
				objectId,
				newCommentContent.trim(),
				parentId,
				messageId
			);
			if (res) {
				newCommentContent = '';
				await loadComments();
			}
		} catch (e) {
			console.error('Failed to create comment', e);
		}
	};

	const startEdit = (comment: any) => {
		editingId = comment.id;
		editContent = comment.content;
	};

	const saveEdit = async (commentId: string) => {
		if (!editContent.trim()) return;

		try {
			const res = await updateComment(token, commentId, editContent.trim());
			if (res) {
				editingId = null;
				editContent = '';
				await loadComments();
			}
		} catch (e) {
			console.error('Failed to update comment', e);
		}
	};

	const cancelEdit = () => {
		editingId = null;
		editContent = '';
	};

	const removeComment = async (id: string) => {
		if (!confirm($i18n.t('Are you sure you want to delete this comment?'))) return;

		try {
			await deleteComment(token, id);
			await loadComments();
		} catch (e) {
			console.error('Failed to delete comment', e);
		}
	};

	const getReplies = (commentId: string) => {
		return comments.filter((c) => c.parent_id === commentId);
	};

	const formatDate = (timestamp: number) => {
		return new Date(timestamp * 1000).toLocaleString();
	};

	onMount(() => {
		loadComments();
	});
</script>

<div class="comment-thread flex flex-col gap-3">
	{#if loading}
		<div class="flex items-center justify-center py-4 text-gray-500 dark:text-gray-400">
			Loading comments...
		</div>
	{:else}
		{#each comments as comment}
			<div
				class="comment-item flex flex-col gap-2 border-b border-gray-100 dark:border-gray-800 pb-3"
				data-comment-id={comment.id}
			>
				<div class="flex items-start gap-3">
					<div class="flex-shrink-0">
						{#if comment.user?.profile_image_url}
							<img
								src={comment.user.profile_image_url}
								alt=""
								class="size-7 rounded-full object-cover"
							/>
						{:else}
							<div class="size-7 rounded-full bg-gray-200 dark:bg-gray-700 flex items-center justify-center text-gray-500 dark:text-gray-400 font-medium text-xs">
								{comment.user?.name?.charAt(0) ?? '?'}
							</div>
						{/if}
					</div>

					<div class="flex-1 min-w-0">
						<div class="flex items-baseline gap-2 mb-1">
							<span class="text-sm font-medium text-gray-900 dark:text-gray-100 truncate">
								{comment.user?.name ?? 'Unknown User'}
							</span>
							<span class="text-xs text-gray-500 dark:text-gray-400">
								{formatDate(comment.created_at)}
							</span>
							{#if editingId === comment.id}
								<button
									class="ml-auto p-1 text-xs text-gray-500 hover:text-gray-700 dark:hover:text-gray-300"
									on:click={cancelEdit}
								>
									Cancel
								</button>
							{/if}
						</div>

						{#if editingId === comment.id}
							<textarea
								bind:value={editContent}
								class="w-full text-sm border border-gray-200 dark:border-gray-700 rounded-lg p-2 focus:outline-none focus:ring-2 focus:ring-blue-500 dark:bg-gray-800/50"
								rows="2"
								placeholder={$i18n.t('Write a comment...')}
							></textarea>
							<div class="flex justify-end gap-2 mt-2">
								<button
									class="px-3 py-1 text-xs text-gray-500 hover:text-gray-700 dark:hover:text-gray-300"
									on:click={cancelEdit}
								>
									{$i18n.t('Cancel')}
								</button>
								<button
									class="px-3 py-1 text-xs text-blue-600 dark:text-blue-400 hover:bg-blue-50 dark:hover:bg-blue-900/20 rounded"
									on:click={() => saveEdit(comment.id)}
								>
									{$i18n.t('Save')}
								</button>
							</div>
						{:else}
							<div class="comment-content text-sm text-gray-700 dark:text-gray-300 whitespace-pre-wrap break-words">
								{comment.content}
							</div>
							<div class="flex items-center gap-3 mt-1.5">
								<button
									class="flex items-center gap-1 text-xs text-gray-500 hover:text-blue-600 dark:hover:text-blue-400 transition"
									on:click={() => startEdit(comment)}
									disabled={comment.user_id !== (localStorage.userId ?? '')}
								>
									{$i18n.t('Edit')}
								</button>
								<button
									class="flex items-center gap-1 text-xs text-gray-500 hover:text-red-500 dark:hover:text-red-400 transition"
									on:click={() => removeComment(comment.id)}
									disabled={
										comment.user_id !== (localStorage.userId ?? '') &&
										localStorage.userRole !== 'admin'
									}
								>
									{$i18n.t('Delete')}
								</button>
								<button
									class="flex items-center gap-1 text-xs text-gray-500 hover:text-blue-600 dark:hover:text-blue-400 transition"
									on:click={() => {
										newCommentContent = `@${comment.user?.name ?? ''} `;
										showThread = true;
									}}
								>
									Reply
								</button>
							</div>
						{/if}
					</div>
				</div>

				{#if editingId !== comment.id}
					<div class="ml-10 border-l-2 border-gray-100 dark:border-gray-800 pl-4">
						{#each getReplies(comment.id) as reply}
							<div
								class="comment-item flex flex-col gap-2 border-b border-gray-50 dark:border-gray-700 pb-2"
								data-comment-id={reply.id}
							>
								<div class="flex items-start gap-3">
									<div class="flex-shrink-0">
										{#if reply.user?.profile_image_url}
											<img
												src={reply.user.profile_image_url}
												alt=""
												class="size-6 rounded-full object-cover"
											/>
										{:else}
											<div class="size-6 rounded-full bg-gray-200 dark:bg-gray-700 flex items-center justify-center text-gray-500 dark:text-gray-400 font-medium text-xs">
												{reply.user?.name?.charAt(0) ?? '?'}
											</div>
										{/if}
									</div>

									<div class="flex-1 min-w-0">
										<div class="flex items-baseline gap-2 mb-1">
											<span class="text-sm font-medium text-gray-900 dark:text-gray-100 truncate">
												{reply.user?.name ?? 'Unknown User'}
											</span>
											<span class="text-xs text-gray-500 dark:text-gray-gray-400">
												{formatDate(reply.created_at)}
											</span>
										</div>
										<div class="comment-content text-sm text-gray-700 dark:text-gray-300 whitespace-pre-wrap break-words">
											{reply.content}
										</div>
										<div class="flex items-center gap-3 mt-1">
											<button
												class="flex items-center gap-1 text-xs text-gray-500 hover:text-blue-600 dark:hover:text-blue-400 transition"
												on:click={() => startEdit(reply)}
												disabled={reply.user_id !== (localStorage.userId ?? '')}
											>
												{$i18n.t('Edit')}
											</button>
											<button
												class="flex items-center gap-1 text-xs text-gray-500 hover:text-red-500 dark:hover:text-red-400 transition"
												on:click={() => removeComment(reply.id)}
												disabled={
													reply.user_id !== (localStorage.userId ?? '') &&
													localStorage.userRole !== 'admin'
												}
											>
												{$i18n.t('Delete')}
											</button>
										</div>
									</div>
								</div>
							</div>
						{/each}
					</div>
				{/if}
			</div>
		{/each}
	{/if}

	<div class="comment-input flex items-start gap-3 pt-3 border-t border-gray-100 dark:border-gray-800">
		<div class="flex-shrink-0">
			<div class="size-7 rounded-full bg-gray-200 dark:bg-gray-700 flex items-center justify-center text-gray-500 dark:text-gray-400 font-medium text-xs">
				{localStorage.userName?.charAt(0) ?? 'U'}
			</div>
		</div>

		<div class="flex-1 min-w-0">
			<textarea
				bind:value={newCommentContent}
				class="w-full text-sm border border-gray-200 dark:border-gray-700 rounded-lg p-3 focus:outline-none focus:ring-2 focus:ring-blue-500 dark:bg-gray-800/50"
				rows="2"
				placeholder={$i18n.t('Write a comment...')}
			></textarea>
			<div class="flex justify-end mt-2">
				<button
					class="px-4 py-1.5 text-sm font-medium text-white bg-blue-600 dark:bg-blue-500 hover:bg-blue-700 dark:hover:bg-blue-600 rounded-lg disabled:opacity-50 disabled:pointer-events-none transition"
					on:click={addComment}
					disabled={!newCommentContent.trim()}
				>
					{$i18n.t('Post')}
				</button>
			</div>
		</div>
	</div>
</div>
