import { WEBUI_API_BASE_URL } from '$lib/constants';

const TELEMETRY_TIMEOUT_MS = 10000;

export const getTelemetry = async (token: string) => {
	let error: any = null;

	const controller = new AbortController();
	const timeoutId = setTimeout(() => controller.abort(), TELEMETRY_TIMEOUT_MS);

	const res = await fetch(`${WEBUI_API_BASE_URL}/utils/telemetry`, {
		method: 'GET',
		headers: {
			'Content-Type': 'application/json',
			Authorization: `Bearer ${token}`
		},
		signal: controller.signal
	})
		.then(async (res) => {
			if (!res.ok) throw await res.json();
			return res.json();
		})
		.catch((err) => {
			clearTimeout(timeoutId);
			console.error(err);
			error = err.detail ?? err;
			return null;
		})
		.finally(() => {
			clearTimeout(timeoutId);
		});

	if (error) {
		throw error;
	}

	return res;
};
