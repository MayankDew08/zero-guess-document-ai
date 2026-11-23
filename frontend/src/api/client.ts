import type { AskResponse } from '../types';

const BASE = (import.meta as any).env?.VITE_API_BASE || 'http://localhost:8000';

export async function ask(question: string, debug = false): Promise<AskResponse> {
  const res = await fetch(`${BASE}/api/ask`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ question, debug }),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function ingestFiles(files: File[]) {
  const fd = new FormData();
  files.forEach(f => fd.append('files', f));
  const res = await fetch(`${BASE}/api/ingest`, { method: 'POST', body: fd });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function ingestSamples() {
  const res = await fetch(`${BASE}/api/ingest/samples`, { method: 'POST' });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function getDocuments() {
  const res = await fetch(`${BASE}/api/documents`);
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function createReport(response: AskResponse) {
  const res = await fetch(`${BASE}/api/report`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ response, format: 'html' }),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export function reportDownloadUrl(reportId: string) {
  return `${BASE}/api/report/${reportId}/download`;
}

export function renderUrl(docId: string, page: number, sentenceId?: string) {
  const q = sentenceId ? `?sentence_id=${encodeURIComponent(sentenceId)}` : '';
  return `${BASE}/api/documents/${encodeURIComponent(docId)}/page/${page}/render${q}`;
}
