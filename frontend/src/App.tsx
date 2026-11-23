import { useCallback, useEffect, useRef, useState } from 'react'
import type { AskResponse, ChatTurn, CorpusSummary, Mode, Workspace, WorkspacesSummary } from './types'
import {
  ask, clearDocuments, createReport, deleteDocument, getDocuments, getHealth, getWorkspacesSummary, ingestSamples, renderUrl, reportDownloadUrl, uploadFiles,
} from './api/client'
import { AnswerBlock, ClarifyCard } from './components/answer'
import type { EvidenceRef } from './components/answer'

const PRESETS: { tag: string; question: string }[] = [
  { tag: 'Active Rule (Amendment Chain)', question: 'What is the late payment fee according to the latest active rule?' },
  { tag: 'Contradiction Alert', question: 'Are there any conflicting rules on late payment fees or grace periods?' },
  { tag: 'Multi-Page & Fee Table', question: 'What are the processing fees, bounce charges, and borrower eligibility conditions in the latest policy?' },
  { tag: 'Calculation with Working', question: 'Calculate the late payment penalty on an overdue EMI of Rs 50,000 for 2 months under the latest active rule.' },
  { tag: 'Hindi Q&A', question: 'नवीनतम सक्रिय नियम के अनुसार विलंब भुगतान शुल्क (late payment fee) क्या है?' },
  { tag: 'Zero-Guessing Abstention', question: 'What is the policy on cryptocurrency collateral for personal loans?' },
  { tag: 'Partial Proof & Safe Abstention', question: 'What is the late payment fee and what is the international SWIFT wire transfer fee under the latest active rule?' },
  { tag: 'Clarifying Follow-Up / Zero-Guessing Math', question: 'Calculate my late payment penalty under the latest active rule.' },
]

const MODES: { id: Mode; label: string; workspace: Workspace; hint: string }[] = [
  { id: 'admin', label: 'Bank Admin', workspace: 'bank_official', hint: 'Manage official policies' },
  { id: 'customer', label: 'Bank Customer', workspace: 'bank_official', hint: 'Read-only Q&A' },
  { id: 'byo', label: 'BYO Private Docs', workspace: 'byo_private', hint: 'Your own PDFs, isolated' },
]

const STAGES = ['Hybrid retrieval (bge-m3 + BM25)', 'Rerank + CRAG gate (bge-reranker)', 'Draft claims (qwen2.5:7b)', 'Resolve citations · NLI · numeric checks', 'Amendment & contradiction analysis']

type Turn = { id: number; question: string; response?: AskResponse; error?: string; loading: boolean }
type Library = { docs: any[]; summary: CorpusSummary | null }
const EMPTY_LIB: Library = { docs: [], summary: null }

function Spinner({ seconds }: { seconds: number }) {
  const stage = Math.min(STAGES.length - 1, Math.floor(seconds / 4))
  return (
    <div role="status" className="border border-sky-900/60 bg-sky-950/30 rounded-xl p-4 text-sm text-sky-200">
      <div className="flex items-center gap-3 mb-3">
        <span className="inline-block h-5 w-5 rounded-full border-2 border-sky-400 border-t-transparent animate-spin" />
        <div className="font-medium">Reading the documents and verifying every claim… <span className="text-sky-300/70 font-normal">{seconds}s (first query loads models)</span></div>
      </div>
      <ol className="grid sm:grid-cols-2 gap-x-4 gap-y-1 text-xs">
        {STAGES.map((s, i) => (
          <li key={s} className={i < stage ? 'text-emerald-300' : i === stage ? 'text-sky-100 font-medium' : 'text-slate-500'}>
            {i < stage ? '✓' : i === stage ? '▸' : '○'} {s}
          </li>
        ))}
      </ol>
    </div>
  )
}

function EvidencePanel({ ev, workspace, onClose, floating }: { ev: EvidenceRef; workspace: Workspace; onClose: () => void; floating: boolean }) {
  const [state, setState] = useState<'loading' | 'ok' | 'error'>('loading')
  const [zoom, setZoom] = useState(1)
  const url = renderUrl(ev.doc_id, ev.page, ev.sentence_id || undefined, workspace)
  useEffect(() => { setState('loading') }, [url])
  useEffect(() => {
    const h = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', h)
    return () => window.removeEventListener('keydown', h)
  }, [onClose])
  const body = (
    <div className={`bg-slate-900 border border-slate-700 flex flex-col ${floating ? 'rounded-xl max-w-3xl w-full max-h-[92vh]' : 'h-full rounded-xl'}`} onClick={e => e.stopPropagation()}>
      <div className="flex items-center justify-between gap-2 px-4 py-3 border-b border-slate-800">
        <div className="text-sm min-w-0"><div className="font-semibold">PDF Evidence</div><div className="text-slate-400 text-xs truncate">{ev.doc_name} · page {ev.page}</div></div>
        <div className="flex items-center gap-1 shrink-0">
          <button onClick={() => setZoom(z => Math.max(0.6, +(z - 0.2).toFixed(1)))} className="px-2 py-1 text-sm rounded bg-slate-800 hover:bg-slate-700" aria-label="Zoom out">−</button>
          <span className="text-xs text-slate-400 w-9 text-center">{Math.round(zoom * 100)}%</span>
          <button onClick={() => setZoom(z => Math.min(2.4, +(z + 0.2).toFixed(1)))} className="px-2 py-1 text-sm rounded bg-slate-800 hover:bg-slate-700" aria-label="Zoom in">+</button>
          <a href={url} target="_blank" rel="noreferrer" className="px-2 py-1 text-xs rounded bg-slate-800 hover:bg-slate-700">Open full ↗</a>
          <button onClick={onClose} className="px-2 py-1 text-sm rounded bg-slate-800 hover:bg-slate-700" aria-label="Close evidence">✕</button>
        </div>
      </div>
      <div className="p-3 border-b border-slate-800">
        <div className="text-[10px] uppercase tracking-wide text-slate-500 mb-1">Verbatim quote (resolved by backend)</div>
        <blockquote className="border-l-4 border-amber-400 bg-amber-300/10 text-slate-100 text-sm p-2 rounded-r">“{ev.quote}”</blockquote>
        <div className="text-[11px] text-slate-500 mt-1">{ev.sentence_id && <code>{ev.sentence_id}</code>}{ev.nli_label && <> · NLI {ev.nli_label}</>}</div>
      </div>
      <div className="flex-1 overflow-auto bg-slate-200 relative">
        {state === 'loading' && <div className="absolute inset-0 flex items-center justify-center text-slate-500 text-sm">Rendering page…</div>}
        {state === 'error' && <div className="p-4 text-red-700 text-sm">Could not render this page.</div>}
        <img src={url} alt={`${ev.doc_name} page ${ev.page} with highlighted evidence`} style={{ width: `${zoom * 100}%`, maxWidth: 'none' }} className="block" onLoad={() => setState('ok')} onError={() => setState('error')} />
      </div>
    </div>
  )
  return floating ? <div className="fixed inset-0 z-50 bg-black/70 flex items-center justify-center p-3" onClick={onClose} role="dialog" aria-modal="true">{body}</div> : body
}

function ModeBanner({ mode, lib, compliance }: { mode: Mode; lib: Library; compliance: WorkspacesSummary | null }) {
  if (mode === 'customer') {
    return (
      <div data-testid="banner-customer" className="rounded-xl border border-emerald-800/70 bg-emerald-950/20 px-4 py-2 text-sm text-emerald-200">
        🔒 Connected to Bank Official Policy Server · Read-Only · {lib.summary?.documents ?? lib.docs.length} Verified Policies
      </div>
    )
  }
  if (mode === 'byo') {
    return (
      <div data-testid="banner-byo" className="rounded-xl border border-violet-800/70 bg-violet-950/20 px-4 py-2 text-sm text-violet-200">
        🗂 Private Local Sandbox — Your PDFs stay isolated from Bank Policies
      </div>
    )
  }
  const b = compliance?.bank_official
  const bad = (b?.unresolved_contradictions_count ?? 0) > 0
  return (
    <div data-testid="banner-admin" className={`rounded-xl border px-4 py-3 ${bad ? 'border-red-800/70 bg-red-950/20' : 'border-emerald-800/70 bg-emerald-950/20'}`}>
      <div className="flex flex-wrap items-center gap-x-6 gap-y-1">
        <div className="text-sm font-semibold">Compliance Audit · Bank Official Corpus</div>
        {b ? (
          <>
            <span className={`text-sm ${bad ? 'text-red-300' : 'text-emerald-300'}`}>⚠ {b.unresolved_contradictions_count} unresolved contradiction{b.unresolved_contradictions_count === 1 ? '' : 's'}</span>
            <span className="text-sm text-indigo-300">⛓ {b.amendment_chains_count} amendment chain{b.amendment_chains_count === 1 ? '' : 's'}</span>
            <span className="text-xs text-slate-400">{b.doc_count} official docs · {b.chunk_count} chunks</span>
          </>
        ) : <span className="text-xs text-slate-500">loading live audit…</span>}
      </div>
      {b && b.contradiction_subjects.length > 0 && <div className="text-xs text-red-200/80 mt-1">Conflicting subjects: {b.contradiction_subjects.join(', ')} — ask “Are there any conflicting rules…” for the quotes.</div>}
    </div>
  )
}

function turnsToHistory(turns: Turn[]): ChatTurn[] {
  return turns.filter(t => t.response).slice(-2).map(t => ({
    role: 'user' as const,
    question: t.question,
    answer_summary: (t.response?.answer || '').slice(0, 300),
    pending_calculation: t.response?.clarification_needed?.pending_calculation ?? null,
  }))
}

export default function App() {
  const [mode, setMode] = useState<Mode>(() => (localStorage.getItem('zg-mode') as Mode) || 'admin')
  const cfg = MODES.find(m => m.id === mode) || MODES[0]
  const workspace = cfg.workspace
  const readOnly = mode === 'customer'

  const [libs, setLibs] = useState<Record<Workspace, Library>>({ bank_official: EMPTY_LIB, byo_private: EMPTY_LIB })
  const [compliance, setCompliance] = useState<WorkspacesSummary | null>(null)
  const [threads, setThreads] = useState<Record<Workspace, Turn[]>>({ bank_official: [], byo_private: [] })
  const [health, setHealth] = useState<any>(null)
  const [pending, setPending] = useState<File[]>([])
  const [dragOver, setDragOver] = useState(false)
  const [progress, setProgress] = useState<{ pct: number; phase: string } | null>(null)
  const [question, setQuestion] = useState('')
  const [asking, setAsking] = useState(false)
  const [busy, setBusy] = useState<string | null>(null)
  const [elapsed, setElapsed] = useState(0)
  const [error, setError] = useState<string | null>(null)
  const [evidence, setEvidence] = useState<EvidenceRef | null>(null)
  const [wide, setWide] = useState(typeof window !== 'undefined' && window.innerWidth >= 1280)
  const timer = useRef<number | null>(null)
  const fileInput = useRef<HTMLInputElement | null>(null)
  const endRef = useRef<HTMLDivElement | null>(null)
  const nextId = useRef(1)

  const lib = libs[workspace]
  const thread = threads[workspace]
  const docs = lib.docs
  const summary = lib.summary

  const refresh = useCallback(async (ws: Workspace) => {
    try { const r = await getDocuments(ws); setLibs(l => ({ ...l, [ws]: { docs: r.documents || [], summary: r.summary || null } })) } catch { /* backend offline */ }
  }, [])
  const refreshCompliance = useCallback(async () => {
    try { setCompliance((await getWorkspacesSummary()).workspaces) } catch { /* backend offline */ }
  }, [])
  useEffect(() => {
    void refresh('bank_official'); void refresh('byo_private'); void refreshCompliance()
    getHealth().then(setHealth).catch(() => setHealth(null))
  }, [refresh, refreshCompliance])
  useEffect(() => {
    const h = () => setWide(window.innerWidth >= 1280)
    window.addEventListener('resize', h)
    return () => window.removeEventListener('resize', h)
  }, [])
  const lastLoading = thread[thread.length - 1]?.loading
  useEffect(() => { endRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' }) }, [thread.length, lastLoading])

  function switchMode(m: Mode) {
    if (m === mode) return
    setMode(m); localStorage.setItem('zg-mode', m)
    setEvidence(null); setPending([]); setError(null); setQuestion('')
    void refreshCompliance()
  }

  const addFiles = (list: FileList | File[]) => {
    const pdfs = Array.from(list).filter(f => f.name.toLowerCase().endsWith('.pdf'))
    if (pdfs.length === 0) { setError('Only PDF files are supported.'); return }
    setError(null); setPending(p => [...p, ...pdfs])
  }
  const afterCorpusChange = async (ws: Workspace) => { await refresh(ws); await refreshCompliance() }

  async function onUpload() {
    if (pending.length === 0 || readOnly) return
    const ws = workspace
    setError(null); setBusy('upload'); setProgress({ pct: 0, phase: 'uploading' })
    try {
      const r = await uploadFiles(pending, (pct, phase) => setProgress({ pct, phase }), ws)
      if (r.errors?.length) setError(r.errors.map((e: any) => `${e.doc_name || ''}: ${e.error}`).join('; '))
      setPending([]); await afterCorpusChange(ws)
    } catch (e: any) { setError(e.message || String(e)) } finally { setBusy(null); setProgress(null) }
  }
  async function onSamples() {
    if (readOnly) return
    const ws = workspace
    setError(null); setBusy('samples')
    try { await ingestSamples(ws); setEvidence(null); await afterCorpusChange(ws) } catch (e: any) { setError(e.message || String(e)) } finally { setBusy(null) }
  }
  async function onDelete(id: string) {
    if (readOnly) return
    const ws = workspace
    setBusy(id)
    try { await deleteDocument(id, ws); setEvidence(e => (e?.doc_id === id ? null : e)); await afterCorpusChange(ws) } catch (e: any) { setError(e.message || String(e)) } finally { setBusy(null) }
  }
  async function onClear() {
    if (readOnly) return
    const ws = workspace
    if (!window.confirm(ws === 'bank_official' ? 'Remove ALL official bank documents?' : 'Remove ALL your private documents?')) return
    setBusy('clear')
    try { await clearDocuments(ws); setEvidence(null); await afterCorpusChange(ws) } catch (e: any) { setError(e.message || String(e)) } finally { setBusy(null) }
  }

  async function onAsk(q: string = question) {
    q = q.trim()
    if (!q || asking) return
    const ws = workspace
    const history = turnsToHistory(threads[ws])
    const id = nextId.current++
    setError(null); setAsking(true); setElapsed(0); setQuestion('')
    setThreads(t => ({ ...t, [ws]: [...t[ws], { id, question: q, loading: true }] }))
    timer.current = window.setInterval(() => setElapsed(s => s + 1), 1000)
    const patch = (p: Partial<Turn>) => setThreads(t => ({ ...t, [ws]: t[ws].map(x => (x.id === id ? { ...x, ...p, loading: false } : x)) }))
    try { patch({ response: await ask(q, { workspace: ws, history }) }) } catch (e: any) { patch({ error: e.message || String(e) }) } finally { setAsking(false); if (timer.current) window.clearInterval(timer.current) }
  }
  const runPreset = (q: string) => { void onAsk(q) }
  const newChat = () => { setThreads(t => ({ ...t, [workspace]: [] })); setEvidence(null); setError(null); setQuestion('') }

  const lastDone = [...thread].reverse().find(t => t.response)?.response
  async function onReport() {
    if (!lastDone) return
    try { const rep = await createReport(lastDone); window.open(reportDownloadUrl(rep.report_id), '_blank') } catch (e: any) { setError(e.message || String(e)) }
  }

  const open = useCallback((c: EvidenceRef) => setEvidence(c), [])
  const closeEv = useCallback(() => setEvidence(null), [])
  const models = health ? `${String(health.model).replace('-instruct', '')} · bge-m3 · bge-reranker-v2-m3 · mDeBERTa-xnli` : 'qwen2.5:7b · bge-m3 · bge-reranker-v2-m3 · mDeBERTa-xnli'
  const awaitingInputs = !!thread[thread.length - 1]?.response?.clarification_needed
  const canManage = !readOnly
  const showPresets = mode !== 'byo'

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100">
      <header className="sticky top-0 z-40 border-b border-slate-800 bg-slate-950/90 backdrop-blur px-4 py-3 flex flex-wrap items-center gap-x-4 gap-y-2">
        <h1 className="text-lg font-bold tracking-tight">Zero-Guessing Document AI</h1>
        <div role="tablist" aria-label="Workspace mode" className="flex rounded-lg border border-slate-700 bg-slate-900 p-0.5">
          {MODES.map(m => (
            <button key={m.id} role="tab" aria-selected={mode === m.id} title={m.hint} onClick={() => switchMode(m.id)}
              className={`px-3 py-1 rounded-md text-xs font-medium transition ${mode === m.id ? (m.id === 'byo' ? 'bg-violet-600 text-white' : m.id === 'customer' ? 'bg-emerald-600 text-white' : 'bg-sky-600 text-white') : 'text-slate-400 hover:text-slate-100'}`}>
              {m.label}
            </button>
          ))}
        </div>
        <span className="text-[11px] px-2 py-0.5 rounded-full border border-emerald-700 bg-emerald-950/40 text-emerald-300 font-medium">100% Local · Offline · Zero Paid APIs</span>
        <span className="text-[11px] text-slate-400" title="Active local models (shared by every workspace)">⚙ {models}</span>
        <span className={`ml-auto text-[11px] ${health?.ollama === 'connected' ? 'text-emerald-400' : 'text-red-400'}`}>● Ollama {health?.ollama || 'unreachable'}</span>
      </header>

      {error && <div className="m-4 p-3 rounded border border-red-800 bg-red-950/40 text-red-200 text-sm">{error} <button className="underline ml-2" onClick={() => setError(null)}>dismiss</button></div>}

      <div className={`grid gap-4 p-4 ${evidence && wide ? 'grid-cols-[18rem_minmax(0,1fr)_30rem]' : 'lg:grid-cols-[18rem_minmax(0,1fr)]'}`}>
        {/* ---------------- sidebar ---------------- */}
        <aside className="space-y-4 lg:sticky lg:top-16 self-start">
          <div className="border border-slate-800 rounded-xl p-3 bg-slate-900/40">
            <h2 className="font-semibold text-sm mb-2">{mode === 'byo' ? 'My Private Documents' : mode === 'customer' ? 'Official Policies' : 'Official Policy Library'}</h2>
            {canManage && (
              <>
                <div
                  onDragOver={e => { e.preventDefault(); setDragOver(true) }} onDragLeave={() => setDragOver(false)}
                  onDrop={e => { e.preventDefault(); setDragOver(false); addFiles(e.dataTransfer.files) }}
                  onClick={() => fileInput.current?.click()}
                  className={`cursor-pointer rounded-lg border-2 border-dashed p-4 text-center text-xs transition ${dragOver ? 'border-sky-400 bg-sky-950/30' : 'border-slate-700 hover:border-slate-500'}`}>
                  Drag &amp; drop PDFs here<br /><span className="text-slate-500">or click to select multiple files</span>
                  <input ref={fileInput} type="file" multiple accept=".pdf,application/pdf" className="hidden" onChange={e => { if (e.target.files) addFiles(e.target.files); e.target.value = '' }} />
                </div>
                {pending.length > 0 && (
                  <div className="mt-2 space-y-1">
                    {pending.map((f, i) => (
                      <div key={i} className="flex items-center justify-between text-xs bg-slate-950/60 border border-slate-800 rounded px-2 py-1">
                        <span className="truncate">{f.name}</span>
                        <button className="text-slate-500 hover:text-red-300 ml-2" onClick={() => setPending(p => p.filter((_, j) => j !== i))} aria-label={`Remove ${f.name}`}>✕</button>
                      </div>
                    ))}
                    <button onClick={onUpload} disabled={busy !== null} className="w-full mt-1 px-3 py-1.5 rounded bg-sky-600 hover:bg-sky-500 disabled:opacity-50 text-sm">Upload &amp; index {pending.length} file{pending.length > 1 ? 's' : ''}</button>
                  </div>
                )}
                {progress && (
                  <div className="mt-2" role="progressbar" aria-valuenow={progress.pct}>
                    <div className="h-1.5 rounded bg-slate-800 overflow-hidden"><div className={`h-full bg-sky-500 ${progress.phase === 'indexing' ? 'animate-pulse' : ''}`} style={{ width: `${progress.pct}%` }} /></div>
                    <div className="text-[11px] text-slate-400 mt-1">{progress.phase === 'uploading' ? `Uploading… ${progress.pct}%` : 'Parsing, chunking & embedding (bge-m3)…'}</div>
                  </div>
                )}
                <div className="flex gap-2 mt-3">
                  {mode === 'admin' && <button onClick={onSamples} disabled={busy !== null} className="flex-1 px-2 py-1.5 rounded bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 text-xs">{busy === 'samples' ? 'Indexing…' : 'Load Demo Sample PDFs'}</button>}
                  <button onClick={onClear} disabled={busy !== null || docs.length === 0} className={`px-2 py-1.5 rounded border border-red-800 text-red-300 hover:bg-red-950/40 disabled:opacity-40 text-xs ${mode === 'byo' ? 'flex-1' : ''}`}>{busy === 'clear' ? '…' : 'Clear All'}</button>
                </div>
              </>
            )}
            <div className={`${canManage ? 'mt-3' : ''} space-y-1`}>
              {docs.length === 0 ? <p className="text-xs text-slate-500">{mode === 'byo' ? 'No private documents yet — drop a PDF above.' : mode === 'customer' ? 'The bank has not published any policies yet.' : 'No documents indexed yet.'}</p> : docs.map((d: any) => (
                <div key={d.doc_id} className="flex items-center justify-between gap-2 text-xs border-b border-slate-800/60 py-1">
                  <div className="min-w-0"><div className="truncate text-slate-200" title={d.doc_name}>{d.doc_name}</div>
                    <div className="flex gap-1 mt-0.5"><span className="px-1.5 rounded bg-slate-800 text-slate-400">{d.num_pages} pg</span><span className="px-1.5 rounded bg-slate-800 text-slate-400">{d.chunks_created} chunks</span></div></div>
                  {canManage && <button onClick={() => onDelete(d.doc_id)} disabled={busy !== null} className="text-slate-500 hover:text-red-300 disabled:opacity-40" title={`Delete ${d.doc_name}`} aria-label={`Delete ${d.doc_name}`}>{busy === d.doc_id ? '…' : '🗑'}</button>}
                </div>
              ))}
            </div>
          </div>
          {summary && (
            <div className="border border-slate-800 rounded-xl p-3 bg-slate-900/40 text-xs">
              <h2 className="font-semibold text-sm mb-2">Corpus health</h2>
              <div className="grid grid-cols-2 gap-x-3 gap-y-1 text-slate-400">
                <span>Documents</span><span className="text-slate-100 text-right">{summary.documents}</span>
                <span>Pages</span><span className="text-slate-100 text-right">{summary.pages}</span>
                <span>Chunks (table)</span><span className="text-slate-100 text-right">{summary.chunks} ({summary.table_chunks})</span>
                <span>Citable sentences</span><span className="text-slate-100 text-right">{summary.sentences}</span>
                <span>Amendment edges</span><span className="text-slate-100 text-right">{summary.amendment_edges}</span>
                <span>Superseded docs</span><span className="text-slate-100 text-right">{summary.superseded_docs}</span>
                <span>Vector index</span><span className={`text-right ${summary.indexed ? 'text-emerald-300' : 'text-amber-300'}`}>{summary.indexed ? 'ready' : 'building…'}</span>
              </div>
            </div>
          )}
        </aside>

        {/* ---------------- workspace ---------------- */}
        <main className="min-w-0 flex flex-col gap-4">
          <ModeBanner mode={mode} lib={lib} compliance={compliance} />

          <div className="flex items-center justify-between">
            <div className="text-xs text-slate-500">{thread.length === 0 ? 'New chat' : `${thread.length} turn${thread.length > 1 ? 's' : ''} · every turn is verified against the PDFs only — earlier answers are never used as evidence`}</div>
            <div className="flex gap-2">
              <button onClick={onReport} disabled={!lastDone} className="px-3 py-1 rounded bg-slate-800 hover:bg-slate-700 disabled:opacity-40 text-xs">Export Audit Report</button>
              <button onClick={newChat} disabled={asking || thread.length === 0} className="px-3 py-1 rounded border border-slate-700 hover:border-sky-500 disabled:opacity-40 text-xs">New Chat</button>
            </div>
          </div>

          <div className="space-y-6" aria-live="polite">
            {thread.length === 0 && (
              <div className="border border-slate-800 rounded-xl p-8 bg-slate-900/20 text-slate-500 text-center">
                {mode === 'byo' ? 'Drop any PDF into your private sandbox, then ask questions. Answers carry verbatim citations or an explicit “I don’t have proof…”.' : 'Pick a demo query to see verified claims, citations, contradictions, amendment chains, calculations and safe abstention.'}
              </div>
            )}
            {thread.map((t, idx) => (
              <section key={t.id} className="space-y-3" data-testid="turn">
                <div className="flex justify-end">
                  <div className="max-w-[85%] rounded-2xl rounded-br-sm bg-sky-900/50 border border-sky-800 px-4 py-2 text-sm">
                    {t.question}
                    {t.response?.rewritten_question && <div className="mt-1 text-[11px] text-sky-300/80 italic" data-testid="resolved-followup">↳ Resolved follow-up: {t.response.rewritten_question}</div>}
                  </div>
                </div>
                {t.loading && <Spinner seconds={elapsed} />}
                {t.error && <div className="p-3 rounded border border-red-800 bg-red-950/40 text-red-200 text-sm">{t.error}</div>}
                {t.response && (
                  <div className="space-y-3">
                    <AnswerBlock answer={t.response} onOpen={open} activeSentenceId={evidence?.sentence_id || undefined} collapseDetails={idx < thread.length - 1} />
                    {t.response.clarification_needed && (
                      <ClarifyCard c={t.response.clarification_needed} active={idx === thread.length - 1} busy={asking} onSubmit={r => void onAsk(r)} />
                    )}
                  </div>
                )}
              </section>
            ))}
            <div ref={endRef} />
          </div>

          <div className="sticky bottom-0 z-30 -mx-1 px-1 pb-3 pt-2 bg-gradient-to-t from-slate-950 via-slate-950 to-slate-950/70">
            {showPresets && (
              <div className="flex flex-wrap gap-2 mb-2">
                {PRESETS.map((p, i) => (
                  <button key={i} onClick={() => runPreset(p.question)} disabled={asking || docs.length === 0} title={p.question}
                    className="px-3 py-1 rounded-full border border-slate-700 bg-slate-950/60 hover:border-sky-500 hover:bg-slate-900 disabled:opacity-40 text-xs">
                    <span className="text-sky-400 mr-1">#{i + 1}</span>{p.tag}
                  </button>
                ))}
              </div>
            )}
            <div className="flex gap-2 items-end">
              <textarea value={question} onChange={e => setQuestion(e.target.value)} rows={2}
                onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); void onAsk() } }}
                className="flex-1 rounded bg-slate-950 border border-slate-700 p-2 text-sm"
                placeholder={awaitingInputs ? 'Reply with the missing inputs, e.g. “Rs 50,000 for 2 months” — or use the form above…' : mode === 'byo' ? 'Ask about your private documents…' : 'Ask a question — or a follow-up like “What about in v1?”…'} />
              <button onClick={() => onAsk()} disabled={asking || !question.trim() || docs.length === 0} className="px-4 py-2 rounded bg-emerald-600 hover:bg-emerald-500 disabled:opacity-50 text-sm h-fit">{asking ? 'Verifying…' : 'Ask'}</button>
            </div>
            {docs.length === 0 && <div className="text-xs text-amber-300 mt-1">{mode === 'byo' ? 'Upload a PDF to your private sandbox first.' : mode === 'customer' ? 'No official policies are published yet — ask your bank admin.' : 'Load the demo PDFs or upload documents first.'}</div>}
          </div>
        </main>

        {/* ---------------- evidence drawer (desktop) ---------------- */}
        {evidence && wide && <aside className="sticky top-16 self-start h-[calc(100vh-5rem)]"><EvidencePanel ev={evidence} workspace={workspace} onClose={closeEv} floating={false} /></aside>}
      </div>
      {evidence && !wide && <EvidencePanel ev={evidence} workspace={workspace} onClose={closeEv} floating />}
    </div>
  )
}
