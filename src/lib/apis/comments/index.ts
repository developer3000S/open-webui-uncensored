import { WEBUI_API_BASE_URL } from '$lib/constants';

export const getComments = async (
	token: string,
	objectType: string,
	objectId: string,
	parentId?: string,
	limit = 100
) => {
	let error: any = null;

	const params = new URLSearchParams();
	params.set('object_type', objectType);
	params.set('object_id', objectId);
	if (parentId !== undefined) params.set('parent_id', parentId);
	params.set('limit', String(limit));

	const res = await fetch(`${WEBUI_API_BASE_URL}/comments?${params.toString()}`, {
		method: 'GET',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`
		}
	})
		.then(async (res) => {
			if (!res.ok) throw await res.json();
			return res.json();
		})
		.catch((err) => {
			error = err;
			console.error(err);
			return null;
		});

	if (error) {
		throw error;
	}

	return res;
};

export const createComment = async (
	token: string,
	objectType: string,
	objectId: string,
	content: string,
	parentId?: string,
	messageId?: string,
	data?: Record<string, any>
) => {
	let error: any = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/comments`, {
		method: 'POST',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`
		},
		body: JSON.stringify({
			object_type: objectType,
			object_id: objectId,
			parent_id: parentId ?? null,
			message_id: messageId ?? null,
			content,
			data
		})
	})
		.then(async (res) => {
			if (!res.ok) throw await res.json();
			return res.json();
		})
		.catch((err) => {
			error = err;
			console.error(err);
			return null;
		});

	if (error) {
		throw error;
	}

	return res;
};

export const updateComment = async (
	token: string,
	commentId: string,
	content: string,
	data?: Record<string, any>
) => {
	let error: any = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/comments/${commentId}`, {
		method: 'PATCH',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`
		},
		body: JSON.stringify({ content, data })
	})
		.then(async (res) => {
			if (!res.ok) throw await res.json();
			return res.json();
		})
		.catch((err) => {
			error = err;
			console.error(err);
			return null;
		});

	if (error) {
		throw error;
	}

	return res;
};

export const deleteComment = async (token: string, commentId: string) => {
	let error: any = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/comments/${commentId}`, {
		method: 'DELETE',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`
		}
	})
		.then(async (res) => {
			if (!res.ok) throw await res.json();
			return res.json();
		})
		.catch((err) => {
			error = err;
			console.error(err);
			return null;
		});

	if (error) {
		throw error;
	}

	return res;
};
