import type { AskResponse, ChatTurn, StageEvent, Workspace, WorkspacesSummary } from '../types';

const BASE = (import.meta as any).env?.VITE_API_BASE || 'http://localhost:8000';
const ws = (workspace: Workspace) => `workspace=${encodeURIComponent(workspace)}`;

async function json<T = any>(res: Response): Promise<T> {
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function ask(question: string, opts: { workspace?: Workspace; history?: ChatTurn[]; debug?: boolean } = {}): Promise<AskResponse> {
  return json(await fetch(`${BASE}/api/ask`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ question, debug: opts.debug ?? false, workspace: opts.workspace ?? 'bank_official', history: opts.history ?? [] }),
  }));
}

/** Same answer as `ask()`, but streams real pipeline progress (SSE `stage` events) before the final `result`.
 *  Falls back to plain `ask()` if the stream route is missing or yields nothing. */
export async function askStream(
  question: string,
  opts: { workspace?: Workspace; history?: ChatTurn[]; debug?: boolean } = {},
  onStage: (e: StageEvent) => void = () => {},
): Promise<AskResponse> {
  const res = await fetch(`${BASE}/api/ask/stream`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' },
    body: JSON.stringify({ question, debug: opts.debug ?? false, workspace: opts.workspace ?? 'bank_official', history: opts.history ?? [] }),
  });
  if (res.status === 404 || res.status === 405) return ask(question, opts);
  if (!res.ok) throw new Error(await res.text());
  if (!res.body) return ask(question, opts);

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buf = '';
  let result: AskResponse | null = null;
  let events = 0;
  const handle = (block: string) => {
    let event = 'message';
    const data: string[] = [];
    for (const line of block.split('\n')) {
      if (line.startsWith('event:')) event = line.slice(6).trim();
      else if (line.startsWith('data:')) data.push(line.slice(5).trimStart());
    }
    if (!data.length) return; // keepalive comment
    const payload = JSON.parse(data.join('\n'));
    events++;
    if (event === 'stage') onStage(payload as StageEvent);
    else if (event === 'result') result = payload as AskResponse;
    else if (event === 'error') throw new Error(payload.detail || 'Pipeline error');
  };
  for (;;) {
    const { value, done } = await reader.read();
    buf += decoder.decode(value, { stream: !done });
    let i: number;
    while ((i = buf.indexOf('\n\n')) >= 0) { handle(buf.slice(0, i)); buf = buf.slice(i + 2); }
    if (done) break;
  }
  if (buf.trim()) handle(buf);
  if (result) return result;
  if (events === 0) return ask(question, opts);
  throw new Error('The answer stream ended before a result arrived');
}

export async function ingestSamples(workspace: Workspace = 'bank_official') {
  return json(await fetch(`${BASE}/api/ingest/samples?${ws(workspace)}`, { method: 'POST' }));
}

export async function getDocuments(workspace: Workspace = 'bank_official') {
  return json(await fetch(`${BASE}/api/documents?${ws(workspace)}`));
}

export async function getWorkspacesSummary(): Promise<{ workspaces: WorkspacesSummary }> {
  return json(await fetch(`${BASE}/api/workspaces/summary`));
}

export async function createReport(response: AskResponse) {
  return json(await fetch(`${BASE}/api/report`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ response, format: 'html' }),
  }));
}

export function reportDownloadUrl(reportId: string) {
  return `${BASE}/api/report/${reportId}/download`;
}

export function renderUrl(docId: string, page: number, sentenceId?: string, workspace: Workspace = 'bank_official') {
  const q = [ws(workspace), sentenceId ? `sentence_id=${encodeURIComponent(sentenceId)}` : ''].filter(Boolean).join('&');
  return `${BASE}/api/documents/${encodeURIComponent(docId)}/page/${page}/render?${q}`;
}

export async function getHealth() {
  return json(await fetch(`${BASE}/api/health`));
}

export async function deleteDocument(docId: string, workspace: Workspace = 'bank_official') {
  return json(await fetch(`${BASE}/api/documents/${encodeURIComponent(docId)}?${ws(workspace)}`, { method: 'DELETE' }));
}

export async function clearDocuments(workspace: Workspace = 'bank_official') {
  return json(await fetch(`${BASE}/api/documents?${ws(workspace)}`, { method: 'DELETE' }));
}

/** Multi-file upload with byte-level progress (fetch cannot report upload progress). */
export function uploadFiles(files: File[], onProgress: (pct: number, phase: 'uploading' | 'indexing') => void, workspace: Workspace = 'bank_official'): Promise<any> {
  return new Promise((resolve, reject) => {
    const fd = new FormData();
    files.forEach(f => fd.append('files', f));
    const xhr = new XMLHttpRequest();
    xhr.open('POST', `${BASE}/api/ingest?${ws(workspace)}`);
    xhr.upload.onprogress = e => { if (e.lengthComputable) onProgress(Math.round((e.loaded / e.total) * 100), 'uploading'); };
    xhr.upload.onload = () => onProgress(100, 'indexing');
    xhr.onload = () => (xhr.status >= 200 && xhr.status < 300 ? resolve(JSON.parse(xhr.responseText)) : reject(new Error(xhr.responseText || `HTTP ${xhr.status}`)));
    xhr.onerror = () => reject(new Error('Network error while uploading'));
    xhr.send(fd);
  });
}

export function openRenderUrl(docId: string, page: number, sentenceId?: string, workspace: Workspace = 'bank_official') {
  return renderUrl(docId, page, sentenceId, workspace);
}
