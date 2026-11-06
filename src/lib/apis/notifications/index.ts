import { WEBUI_API_BASE_URL } from '$lib/constants';

export const getNotifications = async (token: string, unreadOnly = false, limit = 50) => {
	let error: any = null;

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

export const getUnreadNotificationCount = async (token: string) => {
	let error: any = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/notifications/unread-count`, {
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

export const markNotificationRead = async (token: string, notificationId: string) => {
	let error: any = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/notifications/mark-read`, {
		method: 'POST',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`
		},
		body: JSON.stringify({ notification_id: notificationId })
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

export const markAllNotificationsRead = async (token: string) => {
	let error: any = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/notifications/mark-all-read`, {
		method: 'POST',
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
