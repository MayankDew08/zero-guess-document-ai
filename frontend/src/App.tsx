import { useCallback, useEffect, useRef, useState } from 'react'
import type { AskResponse, Calculation, Citation, Claim, CorpusSummary, PipelineTrace } from './types'
import {
  ask, clearDocuments, createReport, deleteDocument, getDocuments, getHealth, ingestSamples, renderUrl, reportDownloadUrl, uploadFiles,
} from './api/client'

const PRESETS: { tag: string; question: string }[] = [
  { tag: 'Active Rule (Amendment Chain)', question: 'What is the late payment fee according to the latest active rule?' },
  { tag: 'Contradiction Alert', question: 'Are there any conflicting rules on late payment fees or grace periods?' },
  { tag: 'Multi-Page & Fee Table', question: 'What are the processing fees, bounce charges, and borrower eligibility conditions in the latest policy?' },
  { tag: 'Calculation with Working', question: 'Calculate the late payment penalty on an overdue EMI of Rs 50,000 for 2 months under the latest active rule.' },
  { tag: 'Hindi Q&A', question: 'नवीनतम सक्रिय नियम के अनुसार विलंब भुगतान शुल्क (late payment fee) क्या है?' },
  { tag: 'Zero-Guessing Abstention', question: 'What is the policy on cryptocurrency collateral for personal loans?' },
  { tag: 'Partial Proof & Safe Abstention', question: 'What is the late payment fee and what is the international SWIFT wire transfer fee under the latest active rule?' },
]

const STAGES = ['Hybrid retrieval (bge-m3 + BM25)', 'Rerank + CRAG gate (bge-reranker)', 'Draft claims (qwen2.5:7b)', 'Resolve citations · NLI · numeric checks', 'Amendment & contradiction analysis']

type EvidenceRef = { doc_id: string; doc_name: string; page: number; sentence_id?: string | null; quote: string; nli_label?: string | null }

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

function StatusBadge({ status }: { status: string }) {
  const colors: Record<string, string> = {
    supported: 'bg-emerald-600/30 text-emerald-300 border-emerald-700',
    contradicted: 'bg-red-600/30 text-red-300 border-red-700',
    blocked: 'bg-amber-600/30 text-amber-300 border-amber-700',
    abstained: 'bg-slate-600/30 text-slate-200 border-slate-500',
    answered: 'bg-emerald-600/30 text-emerald-300 border-emerald-700',
    partially_answered: 'bg-amber-600/30 text-amber-300 border-amber-700',
    confirmed: 'bg-red-600/30 text-red-300 border-red-700',
  }
  return <span className={`px-2 py-0.5 rounded border text-xs ${colors[status] || 'bg-slate-700 text-slate-200 border-slate-600'}`}>{status.replace('_', ' ')}</span>
}

function CitationChip({ c, onOpen, active }: { c: EvidenceRef; onOpen: (c: EvidenceRef) => void; active?: boolean }) {
  return (
    <button onClick={() => onOpen(c)} title="Open highlighted PDF evidence"
      className={`inline-flex items-center gap-1 text-[11px] px-2 py-0.5 rounded-full border cursor-pointer ${active ? 'bg-amber-500/20 border-amber-500 text-amber-200' : 'bg-sky-900/50 hover:bg-sky-800/70 text-sky-200 border-sky-800'}`}>
      📄 {c.doc_name} p.{c.page}
    </button>
  )
}

function EvidencePanel({ ev, onClose, floating }: { ev: EvidenceRef; onClose: () => void; floating: boolean }) {
  const [state, setState] = useState<'loading' | 'ok' | 'error'>('loading')
  const [zoom, setZoom] = useState(1)
  const url = renderUrl(ev.doc_id, ev.page, ev.sentence_id || undefined)
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

function Metric({ label, value, tone, sub }: { label: string; value: string; tone?: string; sub?: string }) {
  return (
    <div className="border border-slate-800 bg-slate-900/50 rounded-xl p-3">
      <div className="text-[10px] uppercase tracking-wide text-slate-500">{label}</div>
      <div className={`text-2xl font-semibold ${tone || 'text-slate-100'}`}>{value}</div>
      {sub && <div className="text-[11px] text-slate-500">{sub}</div>}
    </div>
  )
}

function ClaimCard({ claim, onOpen, activeId }: { claim: Claim; onOpen: (c: EvidenceRef) => void; activeId?: string }) {
  const blocked = claim.status === 'blocked'
  return (
    <div className={`border rounded-lg p-3 ${blocked ? 'border-amber-900/60 bg-amber-950/10' : 'border-slate-800 bg-slate-900/60'}`}>
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className={`text-sm ${blocked ? 'text-slate-400 line-through decoration-amber-700/60' : 'text-slate-100'}`}>{claim.text}</p>
          {claim.text_en && <p className="text-xs text-slate-500 mt-1">Verified English: {claim.text_en}</p>}
        </div>
        <StatusBadge status={claim.status} />
      </div>
      {claim.reason && <p className="text-xs text-amber-300 mt-2">Blocked: {claim.reason}</p>}
      <div className="mt-2 flex flex-wrap gap-1">
        {claim.citations.map((c: Citation, i: number) => <CitationChip key={i} c={c} onOpen={onOpen} active={activeId === c.sentence_id} />)}
      </div>
      <div className="mt-2 space-y-2">
        {claim.citations.map((c: Citation, i: number) => (
          <div key={i} className="text-xs bg-slate-950/60 border border-slate-800 rounded p-2">
            <div className="text-slate-400"><span className="font-medium text-slate-300">{c.doc_name}</span> · p.{c.page} · <code>{c.sentence_id}</code></div>
            <div className="text-slate-300 mt-1">“{c.quote}”</div>
            {c.nli_label && <div className="text-slate-500 mt-1">NLI: {c.nli_label}{c.nli_scores ? ` (entailment ${Number((c.nli_scores as any).entailment || 0).toFixed(2)})` : ''}</div>}
          </div>
        ))}
      </div>
    </div>
  )
}

function CalculationCard({ calc, onOpen }: { calc: Calculation; onOpen: (c: EvidenceRef) => void }) {
  return (
    <div className="border border-emerald-800/60 bg-emerald-950/20 rounded-xl p-4">
      <div className="flex items-center justify-between mb-2">
        <h2 className="font-semibold">🧮 Calculation Working</h2>
        <span className="text-[11px] text-emerald-300/80">deterministic Python math — no LLM arithmetic</span>
      </div>
      <div className="text-xs text-slate-400 mb-2">Formula: <code className="text-slate-200">{calc.formula}</code></div>
      <div className="grid grid-cols-2 md:grid-cols-4 gap-2 mb-3">
        {Object.entries(calc.inputs).filter(([k]) => k !== 'source').map(([k, v]) => (
          <div key={k} className="bg-slate-950/60 border border-slate-800 rounded p-2"><div className="text-[10px] uppercase text-slate-500">{k.replace(/_/g, ' ')}</div><div className="text-sm text-slate-100">{String(v)}</div></div>
        ))}
      </div>
      <ol className="list-decimal ml-5 text-sm text-slate-200 space-y-1">{calc.steps.map((s, i) => <li key={i}>{s}</li>)}</ol>
      <div className="mt-3 text-lg font-semibold text-emerald-300">Result: {calc.result}</div>
      {calc.citation && <div className="mt-2 flex flex-wrap items-center gap-2 text-xs text-slate-400">Rate taken from: <CitationChip c={calc.citation} onOpen={onOpen} /><span className="italic">“{calc.citation.quote}”</span></div>}
      {calc.warnings.map((w, i) => <div key={i} className="mt-2 text-xs text-amber-300 border border-amber-900/50 bg-amber-950/20 rounded p-2">⚠ {w}</div>)}
    </div>
  )
}

function TraceCard({ t }: { t: PipelineTrace }) {
  const [open, setOpen] = useState(false)
  const g1 = t.gate1_retrieval, g2 = t.gate2_citation_resolution, g3 = t.gate3_nli_and_numeric, g4 = t.gate4_lineage_and_conflicts
  const gates = [
    { n: 1, name: 'Retrieval · CRAG', ok: g1.passed, lines: [`${g1.hybrid_candidates} hybrid candidates → ${g1.reranked_kept} kept`, `max rerank ${g1.max_rerank_score == null ? 'n/a' : g1.max_rerank_score.toFixed(3)} vs threshold ${g1.threshold}`] },
    { n: 2, name: 'Citation resolution', ok: g2.rejected_invalid_ids === 0, lines: [`${g2.drafted_claims} drafted`, `${g2.resolved_citations} resolved to stored sentences`, `${g2.rejected_invalid_ids} invalid ids rejected`] },
    { n: 3, name: 'NLI + numeric/date', ok: g3.nli_failed === 0 && g3.numeric_failed === 0, lines: [`NLI ${g3.nli_passed} pass / ${g3.nli_failed} fail`, `numeric ${g3.numeric_passed} pass / ${g3.numeric_failed} fail`] },
    { n: 4, name: 'Lineage & abstention', ok: !g4.abstained, lines: [`${g4.amendment_chains_found} amendment chain(s)`, `${g4.superseded_docs_filtered} superseded doc(s) excluded`, `${g4.unresolved_contradictions} unresolved contradiction(s)`, g4.abstained ? 'abstained' : 'answered'] },
  ]
  return (
    <div className="border border-slate-800 rounded-xl bg-slate-900/40">
      <button onClick={() => setOpen(o => !o)} className="w-full flex items-center justify-between p-4 text-left" aria-expanded={open}>
        <span className="font-semibold">Verification Pipeline Trace (4 Gates)</span>
        <span className="flex items-center gap-2 text-xs text-slate-400">{gates.map(g => <span key={g.n} className={`px-1.5 py-0.5 rounded border ${g.ok ? 'border-emerald-700 text-emerald-300' : 'border-amber-700 text-amber-300'}`}>G{g.n}</span>)}{open ? '▲' : '▼'}</span>
      </button>
      {open && (
        <div className="grid sm:grid-cols-2 gap-3 px-4 pb-4">
          {gates.map(g => (
            <div key={g.n} className={`rounded-lg border p-3 text-xs ${g.ok ? 'border-emerald-900/60 bg-emerald-950/10' : 'border-amber-900/60 bg-amber-950/10'}`}>
              <div className="font-semibold text-slate-100 mb-1">Gate {g.n} · {g.name} <span className={g.ok ? 'text-emerald-300' : 'text-amber-300'}>{g.ok ? 'PASS' : 'FLAG'}</span></div>
              {g.lines.map((l, i) => <div key={i} className="text-slate-400">{l}</div>)}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

export default function App() {
  const [docs, setDocs] = useState<any[]>([])
  const [summary, setSummary] = useState<CorpusSummary | null>(null)
  const [health, setHealth] = useState<any>(null)
  const [pending, setPending] = useState<File[]>([])
  const [dragOver, setDragOver] = useState(false)
  const [progress, setProgress] = useState<{ pct: number; phase: string } | null>(null)
  const [question, setQuestion] = useState(PRESETS[0].question)
  const [answer, setAnswer] = useState<AskResponse | null>(null)
  const [asking, setAsking] = useState(false)
  const [busy, setBusy] = useState<string | null>(null)
  const [elapsed, setElapsed] = useState(0)
  const [error, setError] = useState<string | null>(null)
  const [evidence, setEvidence] = useState<EvidenceRef | null>(null)
  const [wide, setWide] = useState(typeof window !== 'undefined' && window.innerWidth >= 1280)
  const timer = useRef<number | null>(null)
  const fileInput = useRef<HTMLInputElement | null>(null)

  const refresh = useCallback(async () => {
    try { const r = await getDocuments(); setDocs(r.documents || []); setSummary(r.summary || null) } catch { /* backend offline */ }
  }, [])
  useEffect(() => { void refresh(); getHealth().then(setHealth).catch(() => setHealth(null)) }, [refresh])
  useEffect(() => {
    const h = () => setWide(window.innerWidth >= 1280)
    window.addEventListener('resize', h)
    return () => window.removeEventListener('resize', h)
  }, [])

  const addFiles = (list: FileList | File[]) => {
    const pdfs = Array.from(list).filter(f => f.name.toLowerCase().endsWith('.pdf'))
    if (pdfs.length === 0) { setError('Only PDF files are supported.'); return }
    setError(null); setPending(p => [...p, ...pdfs])
  }

  async function onUpload() {
    if (pending.length === 0) return
    setError(null); setBusy('upload'); setProgress({ pct: 0, phase: 'uploading' })
    try {
      const r = await uploadFiles(pending, (pct, phase) => setProgress({ pct, phase }))
      if (r.errors?.length) setError(r.errors.map((e: any) => `${e.doc_name || ''}: ${e.error}`).join('; '))
      setPending([]); await refresh()
    } catch (e: any) { setError(e.message || String(e)) } finally { setBusy(null); setProgress(null) }
  }
  async function onSamples() {
    setError(null); setBusy('samples')
    try { await ingestSamples(); setEvidence(null); await refresh() } catch (e: any) { setError(e.message || String(e)) } finally { setBusy(null) }
  }
  async function onDelete(id: string) {
    setBusy(id)
    try { await deleteDocument(id); setEvidence(e => (e?.doc_id === id ? null : e)); await refresh() } catch (e: any) { setError(e.message || String(e)) } finally { setBusy(null) }
  }
  async function onClear() {
    if (!window.confirm('Remove ALL documents from the corpus?')) return
    setBusy('clear')
    try { await clearDocuments(); setEvidence(null); setAnswer(null); await refresh() } catch (e: any) { setError(e.message || String(e)) } finally { setBusy(null) }
  }

  async function onAsk(q: string = question) {
    if (!q.trim() || asking) return
    setError(null); setAsking(true); setElapsed(0)
    timer.current = window.setInterval(() => setElapsed(s => s + 1), 1000)
    try { setAnswer(await ask(q, false)) } catch (e: any) { setError(e.message || String(e)) } finally { setAsking(false); if (timer.current) window.clearInterval(timer.current) }
  }
  const runPreset = (q: string) => { setQuestion(q); void onAsk(q) }

  async function onReport() {
    if (!answer) return
    try { const rep = await createReport(answer); window.open(reportDownloadUrl(rep.report_id), '_blank') } catch (e: any) { setError(e.message || String(e)) }
  }

  const open = useCallback((c: EvidenceRef) => setEvidence(c), [])
  const closeEv = useCallback(() => setEvidence(null), [])
  const models = health ? `${String(health.model).replace('-instruct', '')} · bge-m3 · bge-reranker-v2-m3 · mDeBERTa-xnli` : 'qwen2.5:7b · bge-m3 · bge-reranker-v2-m3 · mDeBERTa-xnli'
  const faith = answer?.faithfulness_pct

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100">
      <header className="sticky top-0 z-40 border-b border-slate-800 bg-slate-950/90 backdrop-blur px-4 py-3 flex flex-wrap items-center gap-x-4 gap-y-1">
        <h1 className="text-lg font-bold tracking-tight">Zero-Guessing Document AI</h1>
        <span className="text-[11px] px-2 py-0.5 rounded-full border border-emerald-700 bg-emerald-950/40 text-emerald-300 font-medium">100% Local · Offline · Zero Paid APIs</span>
        <span className="text-[11px] text-slate-400" title="Active local models">⚙ {models}</span>
        <span className={`ml-auto text-[11px] ${health?.ollama === 'connected' ? 'text-emerald-400' : 'text-red-400'}`}>● Ollama {health?.ollama || 'unreachable'}</span>
      </header>

      {error && <div className="m-4 p-3 rounded border border-red-800 bg-red-950/40 text-red-200 text-sm">{error} <button className="underline ml-2" onClick={() => setError(null)}>dismiss</button></div>}

      <div className={`grid gap-4 p-4 ${evidence && wide ? 'grid-cols-[18rem_minmax(0,1fr)_30rem]' : 'lg:grid-cols-[18rem_minmax(0,1fr)]'}`}>
        {/* ---------------- sidebar ---------------- */}
        <aside className="space-y-4 lg:sticky lg:top-16 self-start">
          <div className="border border-slate-800 rounded-xl p-3 bg-slate-900/40">
            <h2 className="font-semibold text-sm mb-2">Corpus</h2>
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
              <button onClick={onSamples} disabled={busy !== null} className="flex-1 px-2 py-1.5 rounded bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 text-xs">{busy === 'samples' ? 'Indexing…' : 'Load Demo Sample PDFs'}</button>
              <button onClick={onClear} disabled={busy !== null || docs.length === 0} className="px-2 py-1.5 rounded border border-red-800 text-red-300 hover:bg-red-950/40 disabled:opacity-40 text-xs">{busy === 'clear' ? '…' : 'Clear All'}</button>
            </div>
            <div className="mt-3 space-y-1">
              {docs.length === 0 ? <p className="text-xs text-slate-500">No documents indexed yet.</p> : docs.map((d: any) => (
                <div key={d.doc_id} className="flex items-center justify-between gap-2 text-xs border-b border-slate-800/60 py-1">
                  <div className="min-w-0"><div className="truncate text-slate-200" title={d.doc_name}>{d.doc_name}</div>
                    <div className="flex gap-1 mt-0.5"><span className="px-1.5 rounded bg-slate-800 text-slate-400">{d.num_pages} pg</span><span className="px-1.5 rounded bg-slate-800 text-slate-400">{d.chunks_created} chunks</span></div></div>
                  <button onClick={() => onDelete(d.doc_id)} disabled={busy !== null} className="text-slate-500 hover:text-red-300 disabled:opacity-40" title={`Delete ${d.doc_name}`} aria-label={`Delete ${d.doc_name}`}>{busy === d.doc_id ? '…' : '🗑'}</button>
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
        <main className="space-y-4 min-w-0">
          <div className="border border-slate-800 rounded-xl p-4 bg-slate-900/40">
            <div className="flex flex-wrap gap-2 mb-3">
              {PRESETS.map((p, i) => (
                <button key={i} onClick={() => runPreset(p.question)} disabled={asking || docs.length === 0} title={p.question}
                  className="px-3 py-1.5 rounded-full border border-slate-700 bg-slate-950/60 hover:border-sky-500 hover:bg-slate-900 disabled:opacity-40 text-xs">
                  <span className="text-sky-400 mr-1">#{i + 1}</span>{p.tag}
                </button>
              ))}
            </div>
            <textarea value={question} onChange={e => setQuestion(e.target.value)} rows={2} className="w-full rounded bg-slate-950 border border-slate-700 p-2 text-sm" placeholder="Ask a question about the indexed documents…" />
            <div className="flex gap-2 mt-2">
              <button onClick={() => onAsk()} disabled={asking || !question.trim() || docs.length === 0} className="px-4 py-1.5 rounded bg-emerald-600 hover:bg-emerald-500 disabled:opacity-50 text-sm">{asking ? 'Verifying…' : 'Ask'}</button>
              <button onClick={onReport} disabled={!answer} className="px-3 py-1.5 rounded bg-slate-700 hover:bg-slate-600 disabled:opacity-50 text-sm">Export Audit Report</button>
              {docs.length === 0 && <span className="text-xs text-amber-300 self-center">Load the demo PDFs or upload documents first.</span>}
            </div>
          </div>

          {asking && <Spinner seconds={elapsed} />}
          {!answer && !asking && <div className="border border-slate-800 rounded-xl p-8 bg-slate-900/20 text-slate-500 text-center">Pick a demo query to see verified claims, citations, contradictions, amendment chains, calculations and safe abstention.</div>}

          {answer && (
            <div className={`space-y-4 ${asking ? 'opacity-40' : ''}`}>
              <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                <Metric label="Faithfulness" value={faith == null ? 'N/A' : `${faith}%`} tone={faith === 100 ? 'text-emerald-300' : 'text-amber-300'} sub={`${answer.verified_sentences_count}/${answer.total_shown_sentences} shown claims verified`} />
                <Metric label="Blocked claims" value={String(answer.blocked_claims_count)} tone={answer.blocked_claims_count ? 'text-amber-300' : 'text-slate-100'} sub={answer.draft_support_pct != null ? `draft support ${answer.draft_support_pct}%` : 'nothing drafted'} />
                <Metric label="Confidence" value={answer.confidence == null ? 'N/A' : `${(answer.confidence * 100).toFixed(0)}%`} sub={answer.confidence_breakdown ? `ret ${answer.confidence_breakdown.retrieval?.toFixed(2)} · ver ${answer.confidence_breakdown.verification?.toFixed(2)} · pen ${answer.confidence_breakdown.contradiction_penalty?.toFixed(2)}` : undefined} />
                <Metric label="Status" value={answer.status.replace('_', ' ')} tone={answer.status === 'answered' ? 'text-emerald-300' : answer.status === 'contradicted' ? 'text-red-300' : 'text-amber-300'} />
              </div>

              <div className="border border-slate-800 rounded-xl p-4 bg-slate-900/40">
                {answer.status === 'abstained' ? (
                  <div className="p-4 rounded-lg border border-slate-600 bg-slate-950/60"><div className="text-sm font-semibold mb-1">🛑 Abstained — no guess made</div><p className="text-sm text-slate-200">{answer.answer}</p></div>
                ) : (<><h2 className="font-semibold mb-2">Answer</h2><p className="text-sm text-slate-200 whitespace-pre-wrap">{answer.answer}</p></>)}
                {answer.missing_evidence.length > 0 && (
                  <div className="mt-3 p-3 rounded bg-amber-950/20 border border-amber-900/40">
                    <div className="text-xs font-semibold text-amber-300 mb-1">Missing / Unverified Evidence — no proof found for:</div>
                    <ul className="text-xs text-amber-200 list-disc ml-4">{answer.missing_evidence.map((m, i) => <li key={i}>{m}</li>)}</ul>
                  </div>
                )}
              </div>

              {answer.calculation && <CalculationCard calc={answer.calculation} onOpen={open} />}

              <div className="border border-slate-800 rounded-xl p-4 bg-slate-900/40">
                <h2 className="font-semibold mb-3">Verified Claims &amp; Citations</h2>
                <div className="space-y-3">
                  {answer.claims.length === 0 ? <p className="text-sm text-slate-500">No verified claims to display.</p> : answer.claims.map(c => <ClaimCard key={c.claim_id} claim={c} onOpen={open} activeId={evidence?.sentence_id || undefined} />)}
                </div>
                {answer.blocked_claims.length > 0 && (
                  <div className="mt-4"><h3 className="text-sm font-semibold text-amber-300 mb-2">Blocked Claims (never shown as answer)</h3>
                    <div className="space-y-2">{answer.blocked_claims.map(c => <ClaimCard key={c.claim_id} claim={c} onOpen={open} />)}</div></div>
                )}
              </div>

              <div className="border border-slate-800 rounded-xl p-4 bg-slate-900/40">
                <h2 className="font-semibold mb-3">Contradiction Alerts</h2>
                {answer.contradictions.length === 0 ? <p className="text-sm text-slate-500">No unresolved contradictions detected.</p> : (
                  <div className="space-y-3">
                    {answer.contradictions.map(c => (
                      <div key={c.contradiction_id} className="border border-red-900/40 bg-red-950/10 rounded p-3 text-xs">
                        <div className="flex items-center gap-2 mb-1"><span className="font-semibold text-red-300 capitalize">{c.subject}</span><StatusBadge status={c.status} /></div>
                        <p className="text-slate-300 mb-2">{c.explanation}</p>
                        <div className="grid md:grid-cols-2 gap-2">
                          {c.values.map((v: any, i: number) => (
                            <div key={i} className="bg-slate-950/60 border border-slate-800 p-2 rounded">
                              <div className="mb-1 flex items-center gap-2"><span className="text-[10px] px-1.5 rounded bg-slate-800 text-slate-400">{i === 0 ? 'A' : 'B'}</span><CitationChip c={v} onOpen={open} active={evidence?.sentence_id === v.sentence_id} /></div>
                              <div className="text-slate-200">“{v.quote}”</div>
                            </div>
                          ))}
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>

              <div className="border border-slate-800 rounded-xl p-4 bg-slate-900/40">
                <h2 className="font-semibold mb-3">Amendment Chain</h2>
                {answer.amendment_chains.length === 0 ? <p className="text-sm text-slate-500">No amendment chain involves the retrieved documents.</p> : answer.amendment_chains.map(ch => {
                  const names = ch.doc_names_ordered?.length ? ch.doc_names_ordered : ch.doc_ids_ordered
                  return (
                    <div key={ch.chain_id} className="mb-4">
                      <div className="flex flex-wrap items-center gap-1 mb-2">
                        {names.map((n, i) => (
                          <span key={n} className="flex items-center gap-1">
                            <span className={`px-2 py-1 rounded-lg border text-xs ${n === ch.active_doc_name ? 'border-emerald-600 bg-emerald-950/40 text-emerald-200' : 'border-slate-700 bg-slate-950/60 text-slate-400'}`}>{n}{n === ch.active_doc_name && ' ✓ ACTIVE'}</span>
                            {i < names.length - 1 && <span className="text-slate-600">→</span>}
                          </span>
                        ))}
                      </div>
                      <div className="space-y-2">
                        {ch.edges.map((e: any, i: number) => (
                          <div key={i} className="text-xs border-l-2 border-indigo-700 pl-3">
                            <div className="text-slate-400"><span className="text-slate-100">{e.from_doc_name}</span> <b className="text-indigo-300">{e.relation}</b> <span className="text-slate-100">{e.to_doc_name}</span>{e.effective_date && <> · effective {e.effective_date}</>}</div>
                            <div className="text-slate-200 mt-0.5">“{e.evidence_quote}”</div>
                            <div className="mt-1"><CitationChip c={{ doc_id: e.from_doc_id, doc_name: e.from_doc_name, page: e.evidence_page, sentence_id: e.evidence_sentence_id, quote: e.evidence_quote }} onOpen={open} /></div>
                          </div>
                        ))}
                      </div>
                    </div>
                  )
                })}
              </div>

              {answer.pipeline_trace && <TraceCard t={answer.pipeline_trace} />}
            </div>
          )}
        </main>

        {/* ---------------- evidence drawer (desktop) ---------------- */}
        {evidence && wide && <aside className="sticky top-16 self-start h-[calc(100vh-5rem)]"><EvidencePanel ev={evidence} onClose={closeEv} floating={false} /></aside>}
      </div>
      {evidence && !wide && <EvidencePanel ev={evidence} onClose={closeEv} floating />}
    </div>
  )
}
