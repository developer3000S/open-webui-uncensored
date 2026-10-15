import { WEBUI_API_BASE_URL } from '$lib/constants';

export type CoderConfig = {
	enabled: boolean;
	github_oauth_configured: boolean;
	github_client_id?: string | null;
};

export type CoderConnection = {
	connected: boolean;
	github_login?: string;
	scopes?: string[] | null;
	updated_at?: number;
};

export type CoderRepo = {
	owner: string;
	name: string;
	full_name: string;
	default_branch: string | null;
	private: boolean;
	push_allowed: boolean;
};

export type CoderBranch = {
	name: string;
	sha: string;
};

export type CoderTreeEntry = {
	path: string;
	type: 'blob' | 'tree';
	sha: string;
};

export type CoderFile = {
	path: string;
	sha: string;
	size: number;
	content: string | null;
	binary: boolean;
};

export type CoderChangeFile = {
	action: 'create' | 'update' | 'delete';
	path: string;
	content?: string | null;
};

export type CoderChangeSet = {
	files: CoderChangeFile[];
};

export type CoderValidationResult = {
	valid: boolean;
	changeset?: CoderChangeSet;
	file_count?: number;
	error?: { code: string; message: string; path?: string | null };
};

export type CoderDiffEntry = {
	path: string;
	action: string;
	diff: string;
};

export type CoderExportPreview = {
	valid: boolean;
	diffs: CoderDiffEntry[];
	errors: { path: string; code: string; message: string }[];
};

export type CoderExportForm = {
	owner: string;
	repo: string;
	base_branch: string;
	branch: string;
	commit_message: string;
	changeset: CoderChangeSet;
	idempotency_key: string;
};

export type CoderExportJob = {
	id: string;
	owner: string;
	repo: string;
	base_branch: string;
	branch: string;
	status: string;
	error: string | null;
	commit_sha: string | null;
	pr_url: string | null;
	pr_number: string | null;
	created_at: number;
};

export type CoderAuditEvent = {
	id: string;
	action: string;
	target: string | null;
	payload: Record<string, any> | null;
	created_at: number;
};

const jsonHeaders = (token: string) => ({
	Accept: 'application/json',
	'Content-Type': 'application/json',
	authorization: `Bearer ${token}`
});

const handle = async (res: Response) => {
	if (!res.ok) {
		const body = await res.json().catch(() => null);
		const detail = body?.detail;
		throw new Error(
			typeof detail === 'string' ? detail : detail?.message || `Request failed (${res.status})`
		);
	}
	return res.json();
};

export const getCoderConfig = async (token: string): Promise<CoderConfig> => {
	const res = await fetch(`${WEBUI_API_BASE_URL}/coder/config`, { headers: jsonHeaders(token) });
	return handle(res);
};

export const getGitHubAuthStartUrl = async (token: string): Promise<{ url: string }> => {
	const res = await fetch(`${WEBUI_API_BASE_URL}/coder/github/auth/start`, { headers: jsonHeaders(token) });
	return handle(res);
};

export const getGitHubConnection = async (token: string): Promise<CoderConnection> => {
	const res = await fetch(`${WEBUI_API_BASE_URL}/coder/github/connection`, { headers: jsonHeaders(token) });
	return handle(res);
};

export const disconnectGitHub = async (token: string): Promise<{ status: boolean }> => {
	const res = await fetch(`${WEBUI_API_BASE_URL}/coder/github/connection`, {
		method: 'DELETE',
		headers: jsonHeaders(token)
	});
	return handle(res);
};

export const listCoderRepos = async (token: string, query?: string): Promise<{ repos: CoderRepo[] }> => {
	const params = new URLSearchParams();
	if (query) params.append('query', query);
	const res = await fetch(`${WEBUI_API_BASE_URL}/coder/repos?${params.toString()}`, {
		headers: jsonHeaders(token)
	});
	return handle(res);
};

export const listCoderBranches = async (
	token: string,
	owner: string,
	repo: string
): Promise<{ branches: CoderBranch[] }> => {
	const params = new URLSearchParams({ owner, repo });
	const res = await fetch(`${WEBUI_API_BASE_URL}/coder/branches?${params.toString()}`, {
		headers: jsonHeaders(token)
	});
	return handle(res);
};

export const getCoderTree = async (
	token: string,
	owner: string,
	repo: string,
	branch: string
): Promise<{ tree: CoderTreeEntry[]; project_id: string | null }> => {
	const params = new URLSearchParams({ owner, repo, branch });
	const res = await fetch(`${WEBUI_API_BASE_URL}/coder/tree?${params.toString()}`, {
		headers: jsonHeaders(token)
	});
	return handle(res);
};

export const getCoderFile = async (
	token: string,
	owner: string,
	repo: string,
	path: string,
	branch: string
): Promise<CoderFile> => {
	const params = new URLSearchParams({ owner, repo, path, branch });
	const res = await fetch(`${WEBUI_API_BASE_URL}/coder/file?${params.toString()}`, {
		headers: jsonHeaders(token)
	});
	return handle(res);
};

export const validateCoderChangeset = async (
	token: string,
	files: CoderChangeFile[]
): Promise<CoderValidationResult> => {
	const res = await fetch(`${WEBUI_API_BASE_URL}/coder/changeset/validate`, {
		method: 'POST',
		headers: jsonHeaders(token),
		body: JSON.stringify({ files })
	});
	return handle(res);
};

export const previewCoderExport = async (token: string, form: CoderExportForm): Promise<CoderExportPreview> => {
	const res = await fetch(`${WEBUI_API_BASE_URL}/coder/export/preview`, {
		method: 'POST',
		headers: jsonHeaders(token),
		body: JSON.stringify(form)
	});
	return handle(res);
};

export const startCoderExport = async (
	token: string,
	form: CoderExportForm
): Promise<{ job_id: string; status: string; commit_sha?: string; pr_url?: string; pr_number?: string }> => {
	const res = await fetch(`${WEBUI_API_BASE_URL}/coder/export/start`, {
		method: 'POST',
		headers: jsonHeaders(token),
		body: JSON.stringify(form)
	});
	return handle(res);
};

export const listCoderExportJobs = async (token: string): Promise<{ jobs: CoderExportJob[] }> => {
	const res = await fetch(`${WEBUI_API_BASE_URL}/coder/export/jobs`, { headers: jsonHeaders(token) });
	return handle(res);
};

export const getCoderAuditEvents = async (token: string): Promise<{ events: CoderAuditEvent[] }> => {
	const res = await fetch(`${WEBUI_API_BASE_URL}/coder/audit`, { headers: jsonHeaders(token) });
	return handle(res);
};
