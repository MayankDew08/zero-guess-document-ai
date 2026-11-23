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

export async function getHealth() {
  const res = await fetch(`${BASE}/api/health`);
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function deleteDocument(docId: string) {
  const res = await fetch(`${BASE}/api/documents/${encodeURIComponent(docId)}`, { method: 'DELETE' });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function clearDocuments() {
  const res = await fetch(`${BASE}/api/documents`, { method: 'DELETE' });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

/** Multi-file upload with byte-level progress (fetch cannot report upload progress). */
export function uploadFiles(files: File[], onProgress: (pct: number, phase: 'uploading' | 'indexing') => void): Promise<any> {
  return new Promise((resolve, reject) => {
    const fd = new FormData();
    files.forEach(f => fd.append('files', f));
    const xhr = new XMLHttpRequest();
    xhr.open('POST', `${BASE}/api/ingest`);
    xhr.upload.onprogress = e => { if (e.lengthComputable) onProgress(Math.round((e.loaded / e.total) * 100), 'uploading'); };
    xhr.upload.onload = () => onProgress(100, 'indexing');
    xhr.onload = () => (xhr.status >= 200 && xhr.status < 300 ? resolve(JSON.parse(xhr.responseText)) : reject(new Error(xhr.responseText || `HTTP ${xhr.status}`)));
    xhr.onerror = () => reject(new Error('Network error while uploading'));
    xhr.send(fd);
  });
}

export function openRenderUrl(docId: string, page: number, sentenceId?: string) {
  return renderUrl(docId, page, sentenceId);
}
