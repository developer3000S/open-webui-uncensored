import { WEBUI_API_BASE_URL } from "$lib/constants";

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
  type: "blob" | "tree";
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
  action: "create" | "update" | "delete" | "rename";
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
  Accept: "application/json",
  "Content-Type": "application/json",
  authorization: `Bearer ${token}`,
});

export type ApiErrorDetail = { code?: string; message?: string; path?: string };

const handle = async (res: Response) => {
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    const detail = body?.detail;
    const err: Error & { detail?: ApiErrorDetail | string; status?: number } =
      new Error(
        typeof detail === "string"
          ? detail
          : detail?.message || `Request failed (${res.status})`,
      );
    // preserve structured error info ({code, message, path}) so the UI can map CODER_* codes
    err.detail = detail ?? `Request failed (${res.status})`;
    err.status = res.status;
    throw err;
  }
  return res.json();
};

export const getCoderConfig = async (token: string): Promise<CoderConfig> => {
  const res = await fetch(`${WEBUI_API_BASE_URL}/coder/config`, {
    headers: jsonHeaders(token),
  });
  return handle(res);
};

export const getGitHubAuthStartUrl = async (
  token: string,
  host?: string,
): Promise<{ url: string }> => {
  const params = new URLSearchParams();
  if (host && host !== "github.com") params.append("host", host);
  const qs = params.toString() ? `?${params.toString()}` : "";
  const res = await fetch(
    `${WEBUI_API_BASE_URL}/coder/github/auth/start${qs}`,
    { headers: jsonHeaders(token) },
  );
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

export const listGitHubConnections = async (
  token: string,
): Promise<{ connections: CoderConnectionInfo[] }> => {
  const res = await fetch(`${WEBUI_API_BASE_URL}/coder/github/connections`, {
    headers: jsonHeaders(token),
  });
  return handle(res);
};

export const setDefaultGitHubConnection = async (
  token: string,
  connectionId: string,
): Promise<{ status: boolean }> => {
  const res = await fetch(
    `${WEBUI_API_BASE_URL}/coder/github/connections/${connectionId}/default`,
    {
      method: "POST",
      headers: jsonHeaders(token),
    },
  );
  return handle(res);
};

export const deleteGitHubConnection = async (
  token: string,
  connectionId: string,
): Promise<{ status: boolean }> => {
  const res = await fetch(
    `${WEBUI_API_BASE_URL}/coder/github/connections/${connectionId}`,
    {
      method: "DELETE",
      headers: jsonHeaders(token),
    },
  );
  return handle(res);
};

export const getGitHubConnection = async (
  token: string,
): Promise<CoderConnection> => {
  const res = await fetch(`${WEBUI_API_BASE_URL}/coder/github/connection`, {
    headers: jsonHeaders(token),
  });
  return handle(res);
};

export const disconnectGitHub = async (
  token: string,
): Promise<{ status: boolean }> => {
  const res = await fetch(`${WEBUI_API_BASE_URL}/coder/github/connection`, {
    method: "DELETE",
    headers: jsonHeaders(token),
  });
  return handle(res);
};

export const listCoderRepos = async (
  token: string,
  query?: string,
): Promise<{ repos: CoderRepo[] }> => {
  const params = new URLSearchParams();
  if (query) params.append("query", query);
  const res = await fetch(
    `${WEBUI_API_BASE_URL}/coder/repos?${params.toString()}`,
    {
      headers: jsonHeaders(token),
    },
  );
  return handle(res);
};

export const listCoderBranches = async (
  token: string,
  owner: string,
  repo: string,
): Promise<{ branches: CoderBranch[] }> => {
  const params = new URLSearchParams({ owner, repo });
  const res = await fetch(
    `${WEBUI_API_BASE_URL}/coder/branches?${params.toString()}`,
    {
      headers: jsonHeaders(token),
    },
  );
  return handle(res);
};

export const getCoderTree = async (
  token: string,
  owner: string,
  repo: string,
  branch: string,
): Promise<{ tree: CoderTreeEntry[]; project_id: string | null }> => {
  const params = new URLSearchParams({ owner, repo, branch });
  const res = await fetch(
    `${WEBUI_API_BASE_URL}/coder/tree?${params.toString()}`,
    {
      headers: jsonHeaders(token),
    },
  );
  return handle(res);
};

export const getCoderFile = async (
  token: string,
  owner: string,
  repo: string,
  path: string,
  branch: string,
): Promise<CoderFile> => {
  const params = new URLSearchParams({ owner, repo, path, branch });
  const res = await fetch(
    `${WEBUI_API_BASE_URL}/coder/file?${params.toString()}`,
    {
      headers: jsonHeaders(token),
    },
  );
  return handle(res);
};

export const batchGetCoderFiles = async (
  token: string,
  owner: string,
  repo: string,
  branch: string,
  paths: string[],
): Promise<{
  files: { path: string; content: string }[];
  errors: { path: string; message: string }[];
}> => {
  const res = await fetch(`${WEBUI_API_BASE_URL}/coder/files/batch`, {
    method: "POST",
    headers: jsonHeaders(token),
    body: JSON.stringify({ owner, repo, branch, paths }),
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
  maxResults = 15,
): Promise<{
  query: string;
  scanned_files: number;
  considered_files: number;
  matches: { path: string; hits: { line: number; snippet: string }[] }[];
  errors: { path: string; message: string }[];
}> => {
  const params = new URLSearchParams({
    owner,
    repo,
    branch,
    q,
    max_results: String(maxResults),
  });
  if (paths.length > 0) params.set("paths", paths.join(","));
  const res = await fetch(
    `${WEBUI_API_BASE_URL}/coder/search?${params.toString()}`,
    {
      headers: {
        Accept: "application/json",
        authorization: `Bearer ${token}`,
      },
    },
  );
  return handle(res);
};

export const validateCoderChangeset = async (
  token: string,
  files: CoderChangeFile[],
): Promise<CoderValidationResult> => {
  const res = await fetch(`${WEBUI_API_BASE_URL}/coder/changeset/validate`, {
    method: "POST",
    headers: jsonHeaders(token),
    body: JSON.stringify({ files }),
  });
  return handle(res);
};

export const previewCoderExport = async (
  token: string,
  form: CoderExportForm,
): Promise<CoderExportPreview> => {
  const res = await fetch(`${WEBUI_API_BASE_URL}/coder/export/preview`, {
    method: "POST",
    headers: jsonHeaders(token),
    body: JSON.stringify(form),
  });
  return handle(res);
};

export const startCoderExport = async (
  token: string,
  form: CoderExportForm,
): Promise<{
  job_id: string;
  status: string;
  commit_sha?: string;
  pr_url?: string;
  pr_number?: string;
}> => {
  const res = await fetch(`${WEBUI_API_BASE_URL}/coder/export/start`, {
    method: "POST",
    headers: jsonHeaders(token),
    body: JSON.stringify(form),
  });
  return handle(res);
};

export const listCoderExportJobs = async (
  token: string,
): Promise<{ jobs: CoderExportJob[] }> => {
  const res = await fetch(`${WEBUI_API_BASE_URL}/coder/export/jobs`, {
    headers: jsonHeaders(token),
  });
  return handle(res);
};

export const getCoderAuditEvents = async (
  token: string,
): Promise<{ events: CoderAuditEvent[] }> => {
  const res = await fetch(`${WEBUI_API_BASE_URL}/coder/audit`, {
    headers: jsonHeaders(token),
  });
  return handle(res);
};

// Admin overview of audit events across all users (§14.1)
export const getCoderAdminAuditEvents = async (
  token: string,
  limit = 200,
): Promise<{ events: CoderAdminAuditEvent[] }> => {
  const res = await fetch(
    `${WEBUI_API_BASE_URL}/coder/admin/audit?limit=${limit}`,
    { headers: jsonHeaders(token) },
  );
  return handle(res);
};

// Project management API functions
const textError = async (res: Response): Promise<string> => {
  let detail = `Request failed (${res.status})`;
  try {
    const body = await res.json();
    const d = body?.detail;
    if (typeof d === "string") detail = d;
    else if (d?.message) detail = d.message;
  } catch (_) {
    // Non-JSON error body (e.g. HTML page served by the SPA fallback for an
    // unmounted router) — never surface the raw body to the user.
    detail = `Server returned an invalid response (${res.status} ${res.statusText}). The Coder API may not be available.`;
  }
  const err: Error & { status?: number } = new Error(detail);
  err.status = res.status;
  throw err;
};

export const listProjects = async (token: string): Promise<Project[]> => {
  const res = await fetch(`${WEBUI_API_BASE_URL}/coder/projects`, {
    headers: jsonHeaders(token),
  });
  if (!res.ok) await textError(res);
  const data = await res.json().catch(async () => await textError(res));
  return data.projects || [];
};

export const getProject = async (
  token: string,
  projectId: string,
): Promise<Project> => {
  const res = await fetch(`${WEBUI_API_BASE_URL}/coder/projects/${projectId}`, {
    headers: jsonHeaders(token),
  });
  if (!res.ok) await textError(res);
  return res.json().catch(async () => await textError(res));
};

export const createProject = async (
  token: string,
  form: CreateProjectForm,
): Promise<Project> => {
  const res = await fetch(`${WEBUI_API_BASE_URL}/coder/projects`, {
    method: "POST",
    headers: jsonHeaders(token),
    body: JSON.stringify(form),
  });
  if (!res.ok) await textError(res);
  return res.json().catch(async () => await textError(res));
};

export const deleteProject = async (
  token: string,
  projectId: string,
): Promise<void> => {
  const res = await fetch(`${WEBUI_API_BASE_URL}/coder/projects/${projectId}`, {
    method: "DELETE",
    headers: jsonHeaders(token),
  });
  if (!res.ok) await textError(res);
  await res.json().catch(() => null);
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
  maxResults = 15,
): Promise<{
  query: string;
  mode: string;
  results: CoderSemanticResult[];
  errors: any[];
}> => {
  const params = new URLSearchParams({
    owner,
    repo,
    branch,
    q,
    max_results: String(maxResults),
  });
  const res = await fetch(
    `${WEBUI_API_BASE_URL}/coder/search/semantic?${params.toString()}`,
    {
      headers: jsonHeaders(token),
    },
  );
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
  prNumber: string,
): Promise<{ comments: CoderReviewComment[] }> => {
  const res = await fetch(
    `${WEBUI_API_BASE_URL}/coder/pr/${encodeURIComponent(owner)}/${encodeURIComponent(repo)}/${encodeURIComponent(prNumber)}/comments`,
    { headers: jsonHeaders(token) },
  );
  return handle(res);
};

export const createPRReviewComment = async (
  token: string,
  owner: string,
  repo: string,
  prNumber: string,
  form: { path: string; line: number; body: string; side?: string },
): Promise<{ comment: { id: number; html_url: string } }> => {
  const res = await fetch(
    `${WEBUI_API_BASE_URL}/coder/pr/${encodeURIComponent(owner)}/${encodeURIComponent(repo)}/${encodeURIComponent(prNumber)}/comments`,
    {
      method: "POST",
      headers: jsonHeaders(token),
      body: JSON.stringify({
        owner,
        repo,
        pr_number: prNumber,
        side: "RIGHT",
        ...form,
      }),
    },
  );
  return handle(res);
};

// CI statuses (§22.2)
export type CoderCIStatus = {
  state: string;
  checks: {
    name: string;
    status: string;
    conclusion: string | null;
    url: string | null;
  }[];
  statuses: { context: string; state: string; url: string | null }[];
  sha?: string;
  branch?: string;
};

export const getCoderCIStatus = async (
  token: string,
  owner: string,
  repo: string,
  branch: string,
): Promise<CoderCIStatus> => {
  const params = new URLSearchParams({ owner, repo, branch });
  const res = await fetch(
    `${WEBUI_API_BASE_URL}/coder/ci/status?${params.toString()}`,
    {
      headers: jsonHeaders(token),
    },
  );
  return handle(res);
};

// Export to Gist (§22.2)
export const exportCoderGist = async (
  token: string,
  form: {
    description?: string;
    public?: boolean;
    files: Record<string, string>;
  },
): Promise<{ gist: { id: string; html_url: string; files: string[] } }> => {
  const res = await fetch(`${WEBUI_API_BASE_URL}/coder/export/gist`, {
    method: "POST",
    headers: jsonHeaders(token),
    body: JSON.stringify(form),
  });
  return handle(res);
};

// Auto-generated tests (§22.2)
export const suggestCoderTests = async (
  token: string,
  form: {
    owner: string;
    repo: string;
    title: string;
    body?: string;
    labels?: string[];
  },
): Promise<{
  issue: { number: number; html_url: string };
  test_template: string;
  generated_by_model: boolean;
}> => {
  const res = await fetch(`${WEBUI_API_BASE_URL}/coder/tests/suggest`, {
    method: "POST",
    headers: jsonHeaders(token),
    body: JSON.stringify(form),
  });
  return handle(res);
};

/* ####################
   # Sandbox / Modes / Tasks / Stream metrics (план coder.qwen.ai §A–§E)
   #################### */

export type CoderMode = {
  id: string;
  label?: string;
  name?: string;
  description?: string;
  icon?: string;
};

export type CoderTemplate = {
  id: string;
  title: string;
  mode?: string | null;
  description?: string;
  prompt?: string;
};

export type CoderModesResponse = {
  modes: CoderMode[];
  templates: CoderTemplate[];
};

export type CoderSandboxSession = {
  id: string;
  user_id: string;
  mode: string | null;
  status: string;
  published_share_id: string | null;
  meta: Record<string, any> | null;
  created_at: number;
  updated_at: number;
  last_active_at: number;
  files?: { path: string; size: number }[];
};

export type CoderTaskMeta = {
  id: string;
  user_id: string;
  chat_id: string;
  title: string | null;
  tags: string[] | null;
  mode: string | null;
  is_pinned: boolean;
  is_archived: boolean;
  status: string | null;
  meta: Record<string, any> | null;
  created_at: number;
  updated_at: number;
};

export type CoderTaskMetaForm = {
  title?: string | null;
  tags?: string[] | null;
  mode?: string | null;
  is_pinned?: boolean | null;
  is_archived?: boolean | null;
  status?: string | null;
};

// §B1/§B2: режимы генерации и галерея шаблонов
export const getCoderModes = async (
  token: string,
): Promise<CoderModesResponse> => {
  const res = await fetch(`${WEBUI_API_BASE_URL}/coder/modes`, {
    headers: jsonHeaders(token),
  });
  return handle(res);
};

// §A1: жизненный цикл sandbox-сессий
export const createSandboxSession = async (
  token: string,
  form: { mode?: string | null; template_id?: string | null },
): Promise<CoderSandboxSession> => {
  const res = await fetch(`${WEBUI_API_BASE_URL}/coder/sandbox/session`, {
    method: "POST",
    headers: jsonHeaders(token),
    body: JSON.stringify(form),
  });
  return handle(res);
};

export const listSandboxSessions = async (
  token: string,
): Promise<CoderSandboxSession[]> => {
  const res = await fetch(`${WEBUI_API_BASE_URL}/coder/sandbox/sessions`, {
    headers: jsonHeaders(token),
  });
  return handle(res);
};

export const getSandboxSession = async (
  token: string,
  sessionId: string,
): Promise<CoderSandboxSession> => {
  const res = await fetch(
    `${WEBUI_API_BASE_URL}/coder/sandbox/session/${sessionId}`,
    {
      headers: jsonHeaders(token),
    },
  );
  return handle(res);
};

export const pauseSandboxSession = async (
  token: string,
  sessionId: string,
): Promise<CoderSandboxSession> => {
  const res = await fetch(
    `${WEBUI_API_BASE_URL}/coder/sandbox/session/${sessionId}/pause`,
    {
      method: "POST",
      headers: jsonHeaders(token),
    },
  );
  return handle(res);
};

export const resumeSandboxSession = async (
  token: string,
  sessionId: string,
): Promise<CoderSandboxSession> => {
  const res = await fetch(
    `${WEBUI_API_BASE_URL}/coder/sandbox/session/${sessionId}/resume`,
    {
      method: "POST",
      headers: jsonHeaders(token),
    },
  );
  return handle(res);
};

export const destroySandboxSession = async (
  token: string,
  sessionId: string,
): Promise<{ status: boolean }> => {
  const res = await fetch(
    `${WEBUI_API_BASE_URL}/coder/sandbox/session/${sessionId}`,
    {
      method: "DELETE",
      headers: jsonHeaders(token),
    },
  );
  return handle(res);
};

// §A3: браузерный редактор файлов sandbox
export const readSandboxFile = async (
  token: string,
  sessionId: string,
  path: string,
): Promise<{ path: string; content: string; mime: string }> => {
  const res = await fetch(
    `${WEBUI_API_BASE_URL}/coder/sandbox/session/${sessionId}/file?path=${encodeURIComponent(path)}`,
    { headers: jsonHeaders(token) },
  );
  return handle(res);
};

export const writeSandboxFile = async (
  token: string,
  sessionId: string,
  path: string,
  content: string,
): Promise<{ path: string; size: number }> => {
  const res = await fetch(
    `${WEBUI_API_BASE_URL}/coder/sandbox/session/${sessionId}/file`,
    {
      method: "PUT",
      headers: jsonHeaders(token),
      body: JSON.stringify({ path, content }),
    },
  );
  return handle(res);
};

export const deleteSandboxFile = async (
  token: string,
  sessionId: string,
  path: string,
): Promise<{ status: boolean }> => {
  const res = await fetch(
    `${WEBUI_API_BASE_URL}/coder/sandbox/session/${sessionId}/file?path=${encodeURIComponent(path)}`,
    { method: "DELETE", headers: jsonHeaders(token) },
  );
  return handle(res);
};

// §A5: применение change set модели к sandbox
export const applySandboxChangeset = async (
  token: string,
  sessionId: string,
  files: { action: string; path: string; content?: string }[],
): Promise<{ applied: { path: string; action: string; size: number }[] }> => {
  const res = await fetch(
    `${WEBUI_API_BASE_URL}/coder/sandbox/session/${sessionId}/changeset`,
    {
      method: "POST",
      headers: jsonHeaders(token),
      body: JSON.stringify({ files }),
    },
  );
  return handle(res);
};

// §A2: URL живой превью-панели (iframe src)
export const getSandboxPreviewUrl = (
  sessionId: string,
  version?: number,
): string =>
  `${WEBUI_API_BASE_URL}/coder/sandbox/session/${sessionId}/preview${version !== undefined ? `?v=${version}` : ""}`;

// §A4: публикация одним кликом
export const publishSandboxSession = async (
  token: string,
  sessionId: string,
): Promise<{ share_id: string; url: string; files: number; size: number }> => {
  const res = await fetch(
    `${WEBUI_API_BASE_URL}/coder/sandbox/session/${sessionId}/publish`,
    {
      method: "POST",
      headers: jsonHeaders(token),
    },
  );
  return handle(res);
};

export const getPublishedPageUrl = (shareId: string): string =>
  `${WEBUI_API_BASE_URL}/coder/preview/s/${shareId}`;

// §C1/C2: задачи — список с поиском/фильтрами, pin/archive upsert, удаление
export const listCoderTasks = async (
  token: string,
  opts?: { archived?: boolean; q?: string; tag?: string },
): Promise<CoderTaskMeta[]> => {
  const params = new URLSearchParams();
  if (opts?.archived) params.set("archived", "true");
  if (opts?.q) params.set("q", opts.q);
  if (opts?.tag) params.set("tag", opts.tag);
  const qs = params.toString();
  const res = await fetch(
    `${WEBUI_API_BASE_URL}/coder/tasks${qs ? `?${qs}` : ""}`,
    {
      headers: jsonHeaders(token),
    },
  );
  return handle(res);
};

export const upsertCoderTask = async (
  token: string,
  chatId: string,
  form: CoderTaskMetaForm,
): Promise<CoderTaskMeta> => {
  const res = await fetch(`${WEBUI_API_BASE_URL}/coder/tasks/${chatId}`, {
    method: "POST",
    headers: jsonHeaders(token),
    body: JSON.stringify(form),
  });
  return handle(res);
};

export const deleteCoderTask = async (
  token: string,
  chatId: string,
): Promise<{ status: boolean }> => {
  const res = await fetch(`${WEBUI_API_BASE_URL}/coder/tasks/${chatId}`, {
    method: "DELETE",
    headers: jsonHeaders(token),
  });
  return handle(res);
};

// §B3: автогенерация названия и тегов задачи
export const generateCoderTaskTitle = async (
  token: string,
  chatId: string,
  prompt: string,
): Promise<{ title: string; tags: string[] }> => {
  const res = await fetch(
    `${WEBUI_API_BASE_URL}/coder/tasks/${chatId}/title?prompt=${encodeURIComponent(prompt)}`,
    {
      method: "POST",
      headers: jsonHeaders(token),
    },
  );
  return handle(res);
};

// §B4: follow-up предложения
export const getCoderFollowups = async (
  token: string,
  chatId: string,
  mode?: string | null,
): Promise<{ suggestions: string[] }> => {
  const res = await fetch(
    `${WEBUI_API_BASE_URL}/coder/tasks/${chatId}/followups${mode ? `?mode=${encodeURIComponent(mode)}` : ""}`,
    { headers: jsonHeaders(token) },
  );
  return handle(res);
};

// §E2: метрики стрима (первый чанк, количество чанков)
export const reportCoderStreamMetrics = async (
  token: string,
  data: { first_chunk_ms?: number; chunks?: number; mode?: string },
): Promise<{ status: boolean }> => {
  const params = new URLSearchParams();
  if (data.first_chunk_ms !== undefined)
    params.set("first_chunk_ms", String(data.first_chunk_ms));
  if (data.chunks !== undefined) params.set("chunks", String(data.chunks));
  if (data.mode) params.set("mode", data.mode);
  const res = await fetch(
    `${WEBUI_API_BASE_URL}/coder/stream/metrics?${params.toString()}`,
    {
      method: "POST",
      headers: jsonHeaders(token),
    },
  );
  return handle(res);
};
