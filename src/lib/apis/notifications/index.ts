import { WEBUI_API_BASE_URL } from '$lib/constants';

export const getNotifications = async (token: string, unreadOnly = false, limit = 50) => {
	const params = new URLSearchParams();
	if (unreadOnly) params.set('unread_only', 'true');
	params.set('limit', String(limit));

	const res = await fetch(`${WEBUI_API_BASE_URL}/notifications?${params.toString()}`, {
		method: 'GET',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`
		}
	});

	if (!res.ok) {
		const contentType = res.headers.get('content-type');
		if (contentType && contentType.includes('application/json')) {
			throw await res.json();
		}
		// Для HTML или других типов контента выбрасываем общую ошибку
		throw { message: `Server returned ${res.status} ${res.statusText}`, status: res.status };
	}

	return await res.json();
};

export const getUnreadNotificationCount = async (token: string) => {
	const res = await fetch(`${WEBUI_API_BASE_URL}/notifications/unread-count`, {
		method: 'GET',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`
		}
	});

	if (!res.ok) {
		const contentType = res.headers.get('content-type');
		if (contentType && contentType.includes('application/json')) {
			throw await res.json();
		}
		throw { message: `Server returned ${res.status} ${res.statusText}`, status: res.status };
	}

	return await res.json();
};

export const markNotificationRead = async (token: string, notificationId: string) => {
	const res = await fetch(`${WEBUI_API_BASE_URL}/notifications/mark-read`, {
		method: 'POST',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`
		},
		body: JSON.stringify({ notification_id: notificationId })
	});

	if (!res.ok) {
		const contentType = res.headers.get('content-type');
		if (contentType && contentType.includes('application/json')) {
			throw await res.json();
		}
		throw { message: `Server returned ${res.status} ${res.statusText}`, status: res.status };
	}

	return await res.json();
};

export const markAllNotificationsRead = async (token: string) => {
	const res = await fetch(`${WEBUI_API_BASE_URL}/notifications/mark-all-read`, {
		method: 'POST',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`
		}
	});

	if (!res.ok) {
		const contentType = res.headers.get('content-type');
		if (contentType && contentType.includes('application/json')) {
			throw await res.json();
		}
		throw { message: `Server returned ${res.status} ${res.statusText}`, status: res.status };
	}

	return await res.json();
};

export const createNotification = async (
	token: string,
	type: string,
	title: string,
	content?: string,
	data?: Record<string, any>
) => {
	let error: any = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/notifications`, {
		method: 'POST',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`
		},
		body: JSON.stringify({ type, title, content, data })
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
