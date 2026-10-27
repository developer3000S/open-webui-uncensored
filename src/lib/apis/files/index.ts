import { WEBUI_API_BASE_URL } from '$lib/constants';
import { splitStream } from '$lib/utils';

export type FileProgress = {
	phase?: string;
	percent?: number;
	processed_chunks?: number | null;
	total_chunks?: number | null;
	// Carried on the handover tick so a caller can correlate the row it renders with
	// the server record before `uploadFile` resolves.
	file_id?: string;
};

// Transfer and server-side processing each own half of the bar.
const UPLOAD_SHARE = 0.5;

/** Map a server-side processing tick onto the whole upload+processing bar. */
export const serverProgressToFileProgress = (
	progress: object | null | undefined
): FileProgress | null => {
	if (!progress || typeof progress !== 'object') {
		return null;
	}
	const percent = (progress as FileProgress).percent ?? 0;
	return { ...(progress as FileProgress), percent: UPLOAD_SHARE + UPLOAD_SHARE * percent };
};

export const uploadFile = async (
	token: string,
	file: File,
	metadata?: object | null,
	process?: boolean | null,
	stream: boolean = true,
	onProgress?: ((progress: FileProgress) => void) | null
) => {
	const data = new FormData();
	data.append('file', file);
	if (metadata) {
		data.append('metadata', JSON.stringify(metadata));
	}

	const searchParams = new URLSearchParams();
	if (process !== undefined && process !== null) {
		searchParams.append('process', String(process));
	}

	let error = null;

	// `fetch` exposes no request-body progress hook, so the byte-transfer phase needs XHR.
	const uploadFileRequest = (
		token: string,
		body: FormData,
		url: string,
		onTransfer?: ((fraction: number) => void) | null
	) =>
		new Promise<any>((resolve, reject) => {
			const xhr = new XMLHttpRequest();
			xhr.open('POST', url);
			xhr.setRequestHeader('Accept', 'application/json');
			xhr.setRequestHeader('Authorization', `Bearer ${token}`);

			if (xhr.upload && onTransfer) {
				xhr.upload.onprogress = (event) => {
					if (event.lengthComputable && event.total > 0) {
						onTransfer(event.loaded / event.total);
					}
				};
			}

			xhr.onload = () => {
				let parsed = null;
				try {
					parsed = xhr.responseText ? JSON.parse(xhr.responseText) : null;
				} catch {
					parsed = null;
				}

				if (xhr.status >= 200 && xhr.status < 300) {
					resolve(parsed);
				} else {
					reject(parsed || new Error(`Upload failed with status ${xhr.status}`));
				}
			};

			xhr.onerror = () => reject(new Error('Network error during upload'));
			xhr.onabort = () => reject(new Error('Upload aborted'));

			xhr.send(body);
		});

	let lastUploadPercent = -1;

	const emit = (progress: FileProgress | null) => {
		if (!progress) {
			return;
		}

		// XHR fires transfer progress far more often than the UI can use, and rounding
		// to half-percent steps drops the repeats.  Server ticks are already rate-limited
		// and carry chunk counts, so they always pass through.
		if (progress.phase === 'uploading') {
			const percent = Math.round((progress.percent ?? 0) * 200) / 200;
			if (percent === lastUploadPercent) {
				return;
			}
			lastUploadPercent = percent;
			progress = { ...progress, percent };
		}

		try {
			onProgress?.(progress);
		} catch (err) {
			console.error(err);
		}
	};

	emit({ phase: 'uploading', percent: 0 });

	const res = await uploadFileRequest(
		token,
		data,
		`${WEBUI_API_BASE_URL}/files/?${searchParams.toString()}`,
		(fraction) => emit({ phase: 'uploading', percent: fraction * UPLOAD_SHARE })
	).catch((err) => {
		error = err?.detail || err?.message || err;
		console.error(err);
		return null;
	});

	if (error) {
		throw error;
	}

	if (res && stream) {
		// Announce the handover before opening the status stream. If the stream can never
		// be established (proxy hiccup, 403, a server that died mid-job), the bar would
		// otherwise sit on the last transfer tick — `uploading 0%` for a body that already
		// arrived — and read as "nothing is happening".
		emit({
			phase: 'processing',
			percent: UPLOAD_SHARE,
			processed_chunks: 0,
			total_chunks: null,
			file_id: res.id
		});

		let status = null;
		try {
			status = await getFileProcessStatus(token, res.id);
		} catch {
			status = null;
		}

		if (status && status.ok) {
			const reader = status.body
				.pipeThrough(new TextDecoderStream())
				.pipeThrough(splitStream('\n'))
				.getReader();

			while (true) {
				const { value, done } = await reader.read();
				if (done) {
					break;
				}

				try {
					let lines = value.split('\n');

					for (const line of lines) {
						if (line !== '') {
							console.log(line);
							if (line === 'data: [DONE]') {
								console.log(line);
							} else {
								let data = JSON.parse(line.replace(/^data: /, ''));
								console.log(data);

								if (data?.error) {
									console.error(data.error);
									res.error = data.error;
								}

								if (data?.progress) {
									emit(serverProgressToFileProgress(data.progress));
								}

								if (res?.data) {
									res.data = data;
								}
							}
						}
					}
				} catch (error) {
					console.log(error);
				}
			}
		}
	}

	if (error) {
		throw error;
	}

	return res;
};

export const getFileProcessStatus = async (token: string, id: string) => {
	const queryParams = new URLSearchParams();
	queryParams.append('stream', 'true');

	let error = null;
	const res = await fetch(`${WEBUI_API_BASE_URL}/files/${id}/process/status?${queryParams}`, {
		method: 'GET',
		headers: {
			Accept: 'application/json',
			authorization: `Bearer ${token}`
		}
	}).catch((err) => {
		error = err.detail;
		console.error(err);
		return null;
	});

	if (error) {
		throw error;
	}

	return res;
};

export const uploadDir = async (token: string) => {
	let error = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/files/upload/dir`, {
		method: 'POST',
		headers: {
			Accept: 'application/json',
			authorization: `Bearer ${token}`
		}
	})
		.then(async (res) => {
			if (!res.ok) throw await res.json();
			return res.json();
		})
		.catch((err) => {
			error = err.detail;
			return null;
		});

	if (error) {
		throw error;
	}

	return res;
};

export const getFiles = async (token: string = '', content: boolean = false) => {
	let error = null;

	const searchParams = new URLSearchParams();
	searchParams.append('content', String(content));

	const res = await fetch(`${WEBUI_API_BASE_URL}/files/?${searchParams.toString()}`, {
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
		.then((json) => {
			return json;
		})
		.catch((err) => {
			error = err.detail;
			console.error(err);
			return null;
		});

	if (error) {
		throw error;
	}

	return res;
};

export const searchFiles = async (
	token: string,
	filename: string = '*',
	skip: number = 0,
	limit: number = 50,
	content: boolean = false
) => {
	let error = null;

	const searchParams = new URLSearchParams();
	searchParams.append('filename', filename);
	searchParams.append('skip', String(skip));
	searchParams.append('limit', String(limit));
	searchParams.append('content', String(content));

	const res = await fetch(`${WEBUI_API_BASE_URL}/files/search?${searchParams.toString()}`, {
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
			error = err.detail;
			console.error(err);
			return [];
		});

	if (error) {
		throw error;
	}

	return res;
};

export const getFileCount = async (token: string = '') => {
	let error = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/files/count`, {
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

export const getFileById = async (token: string, id: string) => {
	let error = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/files/${id}`, {
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
		.then((json) => {
			return json;
		})
		.catch((err) => {
			error = err.detail;
			console.error(err);
			return null;
		});

	if (error) {
		throw error;
	}

	return res;
};

export const updateFileDataContentById = async (token: string, id: string, content: string) => {
	let error = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/files/${id}/data/content/update`, {
		method: 'POST',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`
		},
		body: JSON.stringify({
			content: content
		})
	})
		.then(async (res) => {
			if (!res.ok) throw await res.json();
			return res.json();
		})
		.then((json) => {
			return json;
		})
		.catch((err) => {
			error = err.detail;
			console.error(err);
			return null;
		});

	if (error) {
		throw error;
	}

	return res;
};

export const getFileContentById = async (id: string) => {
	let error = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/files/${id}/content`, {
		method: 'GET',
		headers: {
			Accept: 'application/json'
		},
		credentials: 'include'
	})
		.then(async (res) => {
			if (!res.ok) throw await res.json();
			return await res.arrayBuffer();
		})
		.catch((err) => {
			error = err.detail;
			console.error(err);

			return null;
		});

	if (error) {
		throw error;
	}

	return res;
};

export const renameFileById = async (token: string, id: string, filename: string) => {
	let error = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/files/${id}/rename`, {
		method: 'POST',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`
		},
		body: JSON.stringify({ filename })
	})
		.then(async (res) => {
			if (!res.ok) throw await res.json();
			return res.json();
		})
		.catch((err) => {
			error = err.detail;
			console.error(err);
			return null;
		});

	if (error) {
		throw error;
	}

	return res;
};

export const deleteFileById = async (token: string, id: string) => {
	let error = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/files/${id}`, {
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
		.then((json) => {
			return json;
		})
		.catch((err) => {
			error = err.detail;
			console.error(err);
			return null;
		});

	if (error) {
		throw error;
	}

	return res;
};

export const deleteAllFiles = async (token: string) => {
	let error = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/files/all`, {
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
		.then((json) => {
			return json;
		})
		.catch((err) => {
			error = err.detail;
			console.error(err);
			return null;
		});

	if (error) {
		throw error;
	}

	return res;
};
