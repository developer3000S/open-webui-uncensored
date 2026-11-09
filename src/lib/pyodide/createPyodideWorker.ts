import { get } from 'svelte/store';

import { config } from '$lib/stores';
import { PyodideSandboxHost } from '$lib/pyodide/pyodideSandboxHost';
// Worker загружается как внешний chunk, а не инлайн
import PyodideWorker from '$lib/workers/pyodide.worker?worker';

export const createPyodideWorker = (): Worker =>
	get(config)?.features?.enable_pyodide_file_persistence
		? new PyodideWorker()
		: new PyodideSandboxHost() as unknown as Worker;
