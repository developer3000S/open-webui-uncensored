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
	action: 'create' | 'update' | 'delete' | 'rename';
	path: string;
	old_path?: string | null;
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

export type CoderAdminAuditEvent = CoderAuditEvent & {
	user_id: string;
	correlation_id?: string | null;
	ip_address?: string | null;
};

export type Project = {
	id: string;
	owner: string;
	repo: string;
	name?: string | null;
	default_branch: string | null;
	created_at: number;
	updated_at: number;
};

export type CreateProjectForm = {
	owner: string;
	repo: string;
	default_branch: string | null;
	name?: string | null;
};

const jsonHeaders = (token: string) => ({
	Accept: 'application/json',
	'Content-Type': 'application/json',
	authorization: `Bearer ${token}`
});

export type ApiErrorDetail = { code?: string; message?: string; path?: string };

const handle = async (res: Response) => {
	if (!res.ok) {
		const body = await res.json().catch(() => null);
		const detail = body?.detail;
		const err: Error & { detail?: ApiErrorDetail | string; status?: number } = new Error(
			typeof detail === 'string' ? detail : detail?.message || `Request failed (${res.status})`
		);
		// preserve structured error info ({code, message, path}) so the UI can map CODER_* codes
		err.detail = detail ?? `Request failed (${res.status})`;
		err.status = res.status;
		throw err;
	}
	return res.json();
};

export const getCoderConfig = async (token: string): Promise<CoderConfig> => {
	const res = await fetch(`${WEBUI_API_BASE_URL}/coder/config`, { headers: jsonHeaders(token) });
	return handle(res);
};

export const getGitHubAuthStartUrl = async (token: string, host?: string): Promise<{ url: string }> => {
	const params = new URLSearchParams();
	if (host && host !== 'github.com') params.append('host', host);
	const qs = params.toString() ? `?${params.toString()}` : '';
	const res = await fetch(`${WEBUI_API_BASE_URL}/coder/github/auth/start${qs}`, { headers: jsonHeaders(token) });
	return handle(res);
};

export interface CoderConnectionInfo {
	id: string;
	github_login: string | null;
	github_host: string;
	scopes: string[] | null;
	is_default: boolean;
	updated_at: number;
}

export const listGitHubConnections = async (token: string): Promise<{ connections: CoderConnectionInfo[] }> => {
	const res = await fetch(`${WEBUI_API_BASE_URL}/coder/github/connections`, { headers: jsonHeaders(token) });
	return handle(res);
};

export const setDefaultGitHubConnection = async (token: string, connectionId: string): Promise<{ status: boolean }> => {
	const res = await fetch(`${WEBUI_API_BASE_URL}/coder/github/connections/${connectionId}/default`, {
		method: 'POST',
		headers: jsonHeaders(token)
	});
	return handle(res);
};

export const deleteGitHubConnection = async (token: string, connectionId: string): Promise<{ status: boolean }> => {
	const res = await fetch(`${WEBUI_API_BASE_URL}/coder/github/connections/${connectionId}`, {
		method: 'DELETE',
		headers: jsonHeaders(token)
	});
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

export const batchGetCoderFiles = async (
	token: string,
	owner: string,
	repo: string,
	branch: string,
	paths: string[]
): Promise<{ files: { path: string; content: string }[]; errors: { path: string; message: string }[] }> => {
	const res = await fetch(`${WEBUI_API_BASE_URL}/coder/files/batch`, {
		method: 'POST',
		headers: jsonHeaders(token),
		body: JSON.stringify({ owner, repo, branch, paths })
	});
	return handle(res);
};

export const searchCoderRepo = async (
	token: string,
	owner: string,
	repo: string,
	branch: string,
	q: string,
	paths: string[] = [],
	maxResults = 15
): Promise<{
	query: string;
	scanned_files: number;
	considered_files: number;
	matches: { path: string; hits: { line: number; snippet: string }[] }[];
	errors: { path: string; message: string }[];
}> => {
	const params = new URLSearchParams({ owner, repo, branch, q, max_results: String(maxResults) });
	if (paths.length > 0) params.set('paths', paths.join(','));
	const res = await fetch(`${WEBUI_API_BASE_URL}/coder/search?${params.toString()}`, {
		headers: {
			Accept: 'application/json',
			authorization: `Bearer ${token}`
		}
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

// Admin overview of audit events across all users (§14.1)
export const getCoderAdminAuditEvents = async (token: string, limit = 200): Promise<{ events: CoderAdminAuditEvent[] }> => {
	const res = await fetch(`${WEBUI_API_BASE_URL}/coder/admin/audit?limit=${limit}`, { headers: jsonHeaders(token) });
	return handle(res);
};

// Project management API functions
export const listProjects = async (token: string): Promise<Project[]> => {
	const res = await fetch(`${WEBUI_API_BASE_URL}/coder/projects`, { headers: jsonHeaders(token) });
	const data = await handle(res);
	return data.projects || [];
};

export const getProject = async (token: string, projectId: string): Promise<Project> => {
	const res = await fetch(`${WEBUI_API_BASE_URL}/coder/projects/${projectId}`, { headers: jsonHeaders(token) });
	return handle(res);
};

export const createProject = async (token: string, form: CreateProjectForm): Promise<Project> => {
	const res = await fetch(`${WEBUI_API_BASE_URL}/coder/projects`, {
		method: 'POST',
		headers: jsonHeaders(token),
		body: JSON.stringify(form)
	});
	return handle(res);
};

export const deleteProject = async (token: string, projectId: string): Promise<void> => {
	const res = await fetch(`${WEBUI_API_BASE_URL}/coder/projects/${projectId}`, {
		method: 'DELETE',
		headers: jsonHeaders(token)
	});
	await handle(res);
};






// Semantic search (§22.2)
export type CoderSemanticResult = {
	path: string;
	score: number;
	snippet?: string;
	mode?: string;
};

export const semanticSearchCoderRepo = async (
	token: string,
	owner: string,
	repo: string,
	branch: string,
	q: string,
	maxResults = 15
): Promise<{ query: string; mode: string; results: CoderSemanticResult[]; errors: any[] }> => {
	const params = new URLSearchParams({ owner, repo, branch, q, max_results: String(maxResults) });
	const res = await fetch(`${WEBUI_API_BASE_URL}/coder/search/semantic?${params.toString()}`, {
			headers: jsonHeaders(token)
		});
	return handle(res);
};

// Review comments in PR (§22.2)
export type CoderReviewComment = {
	id: number;
	path: string | null;
	line: number | null;
	body: string;
	user: string | null;
	created_at: string | null;
	html_url: string | null;
};

export const listPRReviewComments = async (
	token: string,
	owner: string,
	repo: string,
	prNumber: string
): Promise<{ comments: CoderReviewComment[] }> => {
	const res = await fetch(
		`${WEBUI_API_BASE_URL}/coder/pr/${encodeURIComponent(owner)}/${encodeURIComponent(repo)}/${encodeURIComponent(prNumber)}/comments`,
		{ headers: jsonHeaders(token) }
	);
	return handle(res);
};

export const createPRReviewComment = async (
	token: string,
	owner: string,
	repo: string,
	prNumber: string,
	form: { path: string; line: number; body: string; side?: string }
): Promise<{ comment: { id: number; html_url: string } }> => {
	const res = await fetch(
		`${WEBUI_API_BASE_URL}/coder/pr/${encodeURIComponent(owner)}/${encodeURIComponent(repo)}/${encodeURIComponent(prNumber)}/comments`,
		{
			method: 'POST',
			headers: jsonHeaders(token),
			body: JSON.stringify({ owner, repo, pr_number: prNumber, side: 'RIGHT', ...form })
		}
	);
	return handle(res);
};

// CI statuses (§22.2)
export type CoderCIStatus = {
	state: string;
	checks: { name: string; status: string; conclusion: string | null; url: string | null }[];
	statuses: { context: string; state: string; url: string | null }[];
	sha?: string;
	branch?: string;
};

export const getCoderCIStatus = async (
	token: string,
	owner: string,
	repo: string,
	branch: string
): Promise<CoderCIStatus> => {
	const params = new URLSearchParams({ owner, repo, branch });
	const res = await fetch(`${WEBUI_API_BASE_URL}/coder/ci/status?${params.toString()}`, {
			headers: jsonHeaders(token)
		});
	return handle(res);
};

// Export to Gist (§22.2)
export const exportCoderGist = async (
	token: string,
	form: { description?: string; public?: boolean; files: Record<string, string> }
): Promise<{ gist: { id: string; html_url: string; files: string[] } }> => {
	const res = await fetch(`${WEBUI_API_BASE_URL}/coder/export/gist`, {
			method: 'POST',
			headers: jsonHeaders(token),
			body: JSON.stringify(form)
		});
	return handle(res);
};

// Auto-generated tests (§22.2)
export const suggestCoderTests = async (
	token: string,
	form: { owner: string; repo: string; title: string; body?: string; labels?: string[] }
): Promise<{ issue: { number: number; html_url: string }; test_template: string; generated_by_model: boolean }> => {
	const res = await fetch(`${WEBUI_API_BASE_URL}/coder/tests/suggest`, {
			method: 'POST',
			headers: jsonHeaders(token),
			body: JSON.stringify(form)
		});
	return handle(res);
};
