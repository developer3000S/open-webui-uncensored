import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { uploadFile, serverProgressToFileProgress, type FileProgress } from './index';

describe('serverProgressToFileProgress', () => {
	it('returns null for missing progress', () => {
		expect(serverProgressToFileProgress(null)).toBeNull();
		expect(serverProgressToFileProgress(undefined)).toBeNull();
	});

	it('maps a server tick onto the processing half of the bar', () => {
		expect(
			serverProgressToFileProgress({
				phase: 'embedding',
				percent: 0.4,
				processed_chunks: 2,
				total_chunks: 5
			})
		).toEqual({ phase: 'embedding', percent: 0.7, processed_chunks: 2, total_chunks: 5 });
	});

	it('keeps a completed server tick at the end of the bar', () => {
		expect(serverProgressToFileProgress({ percent: 1 })).toMatchObject({ percent: 1 });
	});

	it('treats a tick without a percentage as just started', () => {
		expect(serverProgressToFileProgress({ phase: 'embedding' })).toMatchObject({ percent: 0.5 });
	});

	// A pending row was already accepted by the server, so a job that has not emitted a tick
	// yet must floor at the handover rather than 0% ("Загрузка 0%" forever after a reload).
	it('floors an entirely silent job at the handover', () => {
		expect(serverProgressToFileProgress({})).toMatchObject({ percent: 0.5 });
	});
});

class FakeXHR {
	static instances: FakeXHR[] = [];

	upload: { onprogress?: ((event: object) => void) | null } = {};
	onload: (() => void) | null = null;
	onerror: (() => void) | null = null;
	onabort: (() => void) | null = null;
	status = 0;
	responseText = '';
	method = '';
	url = '';
	headers: Record<string, string> = {};

	open(method: string, url: string) {
		this.method = method;
		this.url = url;
	}
	setRequestHeader(key: string, value: string) {
		this.headers[key] = value;
	}
	send(_body: unknown) {
		FakeXHR.instances.push(this);
	}
	respondWith(status: number, body: unknown) {
		this.status = status;
		this.responseText = JSON.stringify(body);
		this.onload?.();
	}
	transferProgress(loaded: number, total: number) {
		this.upload.onprogress?.({ lengthComputable: true, loaded, total });
	}
}

const sseResponse = (events: object[]) => ({
	ok: true,
	body: new ReadableStream<Uint8Array>({
		start(controller) {
			const encoder = new TextEncoder();
			for (const event of events) {
				controller.enqueue(encoder.encode(`data: ${JSON.stringify(event)}\n\n`));
			}
			controller.enqueue(encoder.encode('data: [DONE]\n\n'));
			controller.close();
		}
	})
});

describe('uploadFile progress reporting', () => {
	beforeEach(() => {
		FakeXHR.instances = [];
		vi.stubGlobal('XMLHttpRequest', FakeXHR);
		// uploadFile logs every SSE line by design; keep the run output readable.
		vi.spyOn(console, 'log').mockImplementation(() => {});
		vi.spyOn(console, 'error').mockImplementation(() => {});
	});

	afterEach(() => {
		vi.unstubAllGlobals();
		vi.restoreAllMocks();
	});

	const file = new File(['x'], 'doc.pdf', { type: 'application/pdf' });
	const collect = () => {
		const seen: FileProgress[] = [];
		return { seen, onProgress: (progress: FileProgress) => seen.push(progress) };
	};

	it('covers transfer bytes, then the handover, then server ticks', async () => {
		global.fetch = vi
			.fn()
			.mockResolvedValue(
				sseResponse([
					{ status: 'processing' },
					{
						status: 'processing',
						progress: { phase: 'embedding', percent: 0.5, processed_chunks: 3, total_chunks: 6 }
					}
				])
			);

		const { seen, onProgress } = collect();
		const pending = uploadFile('token', file, null, null, true, onProgress);
		const xhr = FakeXHR.instances[0];

		expect(seen).toEqual([{ phase: 'uploading', percent: 0 }]);
		xhr.transferProgress(500, 1000);
		xhr.transferProgress(500, 1000);
		expect(seen.filter((entry) => entry.phase === 'uploading')).toEqual([
			{ phase: 'uploading', percent: 0 },
			{ phase: 'uploading', percent: 0.25 }
		]);

		xhr.respondWith(200, { id: 'file-1' });
		const res = await pending;

		expect(res).toEqual({ id: 'file-1' });
		expect(seen).toEqual([
			{ phase: 'uploading', percent: 0 },
			{ phase: 'uploading', percent: 0.25 },
			{
				phase: 'processing',
				percent: 0.5,
				processed_chunks: 0,
				total_chunks: null,
				file_id: 'file-1'
			},
			{ phase: 'embedding', percent: 0.75, processed_chunks: 3, total_chunks: 6 }
		]);
	});

	it('still hands over to the processing phase when the status stream cannot open', async () => {
		// A failed status stream used to leave the bar on the last transfer tick —
		// "Uploading 0%" for a body the server already took, with nothing ever moving it.
		global.fetch = vi.fn().mockResolvedValue({ ok: false, status: 502, body: null });

		const { seen, onProgress } = collect();
		const pending = uploadFile('token', file, null, null, true, onProgress);
		FakeXHR.instances[0].respondWith(200, { id: 'file-1' });

		await pending;
		const phases = seen.map((entry) => entry.phase);
		expect(phases[phases.length - 1]).toBe('processing');
		expect(seen[seen.length - 1]).toMatchObject({ file_id: 'file-1', percent: 0.5 });
	});

	it('hands over even when opening the status stream throws', async () => {
		global.fetch = vi.fn().mockRejectedValue(new TypeError('Failed to fetch'));

		const { seen, onProgress } = collect();
		const pending = uploadFile('token', file, null, null, true, onProgress);
		FakeXHR.instances[0].respondWith(200, { id: 'file-9' });

		await expect(pending).resolves.toEqual({ id: 'file-9' });
		expect(seen[seen.length - 1]).toMatchObject({ phase: 'processing', file_id: 'file-9' });
	});

	it('rounds transfer progress to half-percent steps', async () => {
		global.fetch = vi.fn().mockResolvedValue(sseResponse([{ status: 'completed' }]));

		const { seen, onProgress } = collect();
		const pending = uploadFile('token', file, null, null, true, onProgress);
		const xhr = FakeXHR.instances[0];

		xhr.transferProgress(1, 3);
		expect(seen[1]).toEqual({ phase: 'uploading', percent: 0.165 });

		xhr.respondWith(200, { id: 'file-1' });
		await pending;
	});

	it('ignores transfer events that carry no total', async () => {
		global.fetch = vi.fn().mockResolvedValue(sseResponse([{ status: 'completed' }]));

		const { seen, onProgress } = collect();
		const pending = uploadFile('token', file, null, null, true, onProgress);
		const xhr = FakeXHR.instances[0];

		xhr.upload.onprogress?.({ lengthComputable: false, loaded: 1024, total: 0 });
		expect(seen).toEqual([{ phase: 'uploading', percent: 0 }]);

		xhr.respondWith(200, { id: 'file-1' });
		await pending;
	});

	it('stops at the transfer phase when the server rejects the upload', async () => {
		global.fetch = vi.fn();
		const { seen, onProgress } = collect();
		const pending = uploadFile('token', file, null, null, true, onProgress).catch((error) => error);

		const xhr = FakeXHR.instances[0];
		xhr.transferProgress(900, 1000);
		xhr.respondWith(413, { detail: 'File too large' });

		expect(await pending).toBe('File too large');
		expect(seen.map((entry) => entry.phase)).toEqual(['uploading', 'uploading']);
		expect(global.fetch).not.toHaveBeenCalled();
	});

	it('keeps streaming when the callback throws', async () => {
		global.fetch = vi.fn().mockResolvedValue(sseResponse([{ status: 'completed' }]));

		const onProgress = vi
			.fn()
			.mockImplementationOnce(() => {
				throw new Error('render failed');
			})
			.mockImplementationOnce(() => {
				throw new Error('render failed');
			});

		const pending = uploadFile('token', file, null, null, true, onProgress);
		FakeXHR.instances[0].respondWith(200, { id: 'file-1' });

		await expect(pending).resolves.toEqual({ id: 'file-1' });
		// 'uploading 0' + the post-transfer 'processing' handover; the SSE tick has no progress.
		expect(onProgress).toHaveBeenCalledTimes(2);
	});

	it('sends the file and metadata as form data with the auth header', async () => {
		global.fetch = vi.fn().mockResolvedValue(sseResponse([{ status: 'completed' }]));

		const pending = uploadFile('token', file, { collection_name: 'kb-1' }, false, true, null);
		const xhr = FakeXHR.instances[0];

		expect(xhr.method).toBe('POST');
		expect(xhr.url).toContain('/files/?process=false');
		expect(xhr.headers).toMatchObject({
			Accept: 'application/json',
			Authorization: 'Bearer token'
		});
		expect(xhr.upload.onprogress).toBeTypeOf('function');

		xhr.respondWith(200, { id: 'file-1' });
		await pending;
	});
});
