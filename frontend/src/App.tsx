import { useCallback, useEffect, useRef, useState } from 'react'
import { PanelLeft, ShieldCheck, SquarePen, XCircle } from 'lucide-react'
import type { AskResponse, ChatTurn, CorpusSummary, Mode, Workspace, WorkspacesSummary } from './types'
import {
  ask, clearDocuments, createReport, deleteDocument, getDocuments, getHealth, getWorkspacesSummary, ingestSamples, renderUrl, reportDownloadUrl, uploadFiles,
} from './api/client'
import { TurnAnswer } from './components/answer'
import type { EvidenceRef } from './components/answer'
import { ComplianceBanner, Composer, EvidenceDrawer, LibrarySidebar, MODES, SuggestionChips, TopBar } from './components/shell'
import type { LibraryDoc, Suggestion } from './components/shell'

const PRESETS: Suggestion[] = [
  { tag: 'Active Rule (Amendment Chain)', question: 'What is the late payment fee according to the latest active rule?' },
  { tag: 'Contradiction Alert', question: 'Are there any conflicting rules on late payment fees or grace periods?' },
  { tag: 'Multi-Page & Fee Table', question: 'What are the processing fees, bounce charges, and borrower eligibility conditions in the latest policy?' },
  { tag: 'Calculation with Working', question: 'Calculate the late payment penalty on an overdue EMI of Rs 50,000 for 2 months under the latest active rule.' },
  { tag: 'Hindi Q&A', question: 'नवीनतम सक्रिय नियम के अनुसार विलंब भुगतान शुल्क (late payment fee) क्या है?' },
  { tag: 'Zero-Guessing Abstention', question: 'What is the policy on cryptocurrency collateral for personal loans?' },
  { tag: 'Partial Proof & Safe Abstention', question: 'What is the late payment fee and what is the international SWIFT wire transfer fee under the latest active rule?' },
  { tag: 'Clarifying Follow-Up / Zero-Guessing Math', question: 'Calculate my late payment penalty under the latest active rule.' },
]

type Turn = { id: number; question: string; response?: AskResponse; error?: string; loading: boolean }
type Library = { docs: any[]; summary: CorpusSummary | null }
const EMPTY_LIB: Library = { docs: [], summary: null }


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
  const [progress, setProgress] = useState<{ pct: number; phase: string } | null>(null)
  const [question, setQuestion] = useState('')
  const [asking, setAsking] = useState(false)
  const [busy, setBusy] = useState<string | null>(null)
  const [elapsed, setElapsed] = useState(0)
  const [error, setError] = useState<string | null>(null)
  const [evidence, setEvidence] = useState<EvidenceRef | null>(null)
  const [libOpen, setLibOpen] = useState(false)
  const timer = useRef<number | null>(null)
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
  const lastLoading = thread[thread.length - 1]?.loading
  useEffect(() => { endRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' }) }, [thread.length, lastLoading])

  function switchMode(m: Mode) {
    if (m === mode) return
    setMode(m); localStorage.setItem('zg-mode', m)
    setEvidence(null); setPending([]); setError(null); setQuestion(''); setLibOpen(false)
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
  const newChat = () => { setThreads(t => ({ ...t, [workspace]: [] })); setEvidence(null); setError(null); setQuestion('') }

  async function onExportReport(requestId: string) {
    const resp = thread.find(t => t.response?.request_id === requestId)?.response
    if (!resp) return
    try { const rep = await createReport(resp); window.open(reportDownloadUrl(rep.report_id), '_blank') } catch (e: any) { setError(e.message || String(e)) }
  }
  /** Inline calculation form -> the same chat reply a user could type; history carries pending_calculation. */
  function onClarifySubmit(_baseQuestion: string, v: Record<string, string>) {
    const parts: string[] = []
    if (v.principal) parts.push(`Rs ${Number(v.principal)}`)
    if (v.months) parts.push(`${Number(v.months)} ${Number(v.months) === 1 ? 'month' : 'months'}`)
    void onAsk(parts.join(' for '))
  }
  const bankMode = useRef<Mode>(mode === 'customer' ? 'customer' : 'admin')
  if (mode !== 'byo') bankMode.current = mode
  const switchWorkspace = (ws: Workspace) => switchMode(ws === 'byo_private' ? 'byo' : bankMode.current)

  const open = useCallback((c: EvidenceRef) => setEvidence(c), [])
  const closeEv = useCallback(() => setEvidence(null), [])
  const models = health ? `${String(health.model).replace('-instruct', '')} · bge-m3 · bge-reranker-v2-m3 · mDeBERTa-xnli` : 'qwen2.5:7b · bge-m3 · bge-reranker-v2-m3 · mDeBERTa-xnli'
  const awaitingInputs = !!thread[thread.length - 1]?.response?.clarification_needed
  const canManage = !readOnly
  const showPresets = mode !== 'byo'
  const ollama: string | null = health ? String(health.ollama) : null

  const evUrl = evidence ? renderUrl(evidence.doc_id, evidence.page, evidence.sentence_id || undefined, workspace) : ''
  const placeholder = awaitingInputs ? 'Reply with the missing inputs, e.g. “Rs 50,000 for 2 months” — or use the form above…' : mode === 'byo' ? 'Ask about your private documents…' : 'Ask a question — or a follow-up like “What about in v1?”…'
  const noDocsHint = mode === 'byo' ? 'Upload a PDF to your private sandbox first.' : mode === 'customer' ? 'No official policies are published yet — ask your bank admin.' : 'Load the demo PDFs or upload documents first.'

  return (
    <div className="flex h-screen flex-col overflow-hidden bg-[#0A0E14] font-sans text-zinc-100">
      <TopBar workspace={workspace} mode={mode} ollama={ollama} models={models} onWorkspaceChange={switchWorkspace} onModeChange={switchMode} onToggleLibrary={() => setLibOpen(o => !o)} />
      <ComplianceBanner mode={mode} stats={compliance?.bank_official ?? null} docCount={summary?.documents ?? docs.length} />
      <div className="relative flex min-h-0 flex-1">
        <LibrarySidebar mode={mode} docs={docs as LibraryDoc[]} summary={summary} pending={pending} progress={progress} busy={busy} canManage={canManage}
          open={libOpen} onClose={() => setLibOpen(false)} onPickFiles={addFiles} onRemovePending={i => setPending(p => p.filter((_, j) => j !== i))}
          onUpload={onUpload} onLoadSamples={onSamples} onDeleteDoc={onDelete} onClear={onClear} />
        <main className="flex min-w-0 flex-1 flex-col">
          <div className="min-h-0 flex-1 overflow-y-auto">
            <div className="mx-auto w-full max-w-[900px] px-3 pb-6 pt-5 sm:px-6 sm:pt-7">
              <div className="mb-5 flex items-center justify-between gap-4">
                <div>
                  <p className="flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-[0.13em] text-emerald-300"><ShieldCheck aria-hidden="true" size={13} />Verification-first session</p>
                  <h2 className="mt-1 text-lg font-semibold tracking-tight text-zinc-100">Policy evidence review</h2>
                </div>
                <div className="flex items-center gap-3">
                  <span className="hidden text-[10px] text-zinc-600 md:block">{thread.length === 0 ? 'New chat' : `${thread.length} turn${thread.length > 1 ? 's' : ''} · earlier answers are never used as evidence`}</span>
                  <button type="button" onClick={newChat} disabled={asking || thread.length === 0} className="inline-flex items-center gap-1.5 rounded-lg bg-[#10151D] px-3 py-2 text-[11px] text-zinc-300 transition hover:bg-white/[0.07] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-500/40 disabled:opacity-40"><SquarePen aria-hidden="true" size={13} />New chat</button>
                </div>
              </div>

              {error ? (
                <div role="alert" className="mb-4 flex items-start gap-2 rounded-xl bg-rose-400/[0.07] px-4 py-3 text-sm text-rose-200 ring-1 ring-inset ring-rose-400/20">
                  <XCircle aria-hidden="true" size={15} className="mt-0.5 shrink-0" /><span className="min-w-0 flex-1 break-words">{error}</span>
                  <button type="button" className="text-xs underline" onClick={() => setError(null)}>dismiss</button>
                </div>
              ) : null}

              {thread.length === 0 ? (
                <div className="mb-8 rounded-xl bg-[#10151D] px-5 py-7 text-center ring-1 ring-inset ring-white/[0.06]">
                  <div className="mx-auto flex h-10 w-10 items-center justify-center rounded-xl bg-emerald-400/10 text-emerald-300"><ShieldCheck aria-hidden="true" size={20} /></div>
                  <h3 className="mt-3 text-sm font-semibold text-zinc-100">Ask only what the corpus can prove</h3>
                  <p className="mx-auto mt-1 max-w-md text-xs leading-5 text-zinc-500">{mode === 'byo' ? 'Drop any PDF into your private sandbox, then ask questions. Answers carry verbatim citations or an explicit “I don’t have proof…”.' : 'Answers stay local. Every quote is attached to its source page; uncertain claims are withheld instead of guessed.'}</p>
                  {showPresets ? <div className="mt-5"><SuggestionChips suggestions={PRESETS} disabled={asking || docs.length === 0} onSelect={q => void onAsk(q)} /></div> : null}
                  {docs.length === 0 ? <button type="button" onClick={() => setLibOpen(true)} className="mt-4 inline-flex items-center gap-1.5 text-[11px] text-amber-300 lg:pointer-events-none"><PanelLeft aria-hidden="true" size={12} />{noDocsHint}</button> : null}
                </div>
              ) : null}

              <div className="space-y-6" aria-live="polite">
                {thread.map((t, idx) => (
                  <section key={t.id} className="space-y-3" data-testid="turn" aria-label={`Conversation turn: ${t.question}`}>
                    <div className="flex justify-end">
                      <div className="max-w-[80%] rounded-2xl rounded-br-md bg-[#202833] px-3.5 py-2.5 sm:max-w-[70%]">
                        <p className="whitespace-pre-wrap text-[13px] leading-5 text-zinc-100">{t.question}</p>
                        {t.response?.rewritten_question ? <p data-testid="resolved-followup" className="mt-1.5 text-[10px] italic leading-4 text-zinc-500">↳ resolved: {t.response.rewritten_question}</p> : null}
                      </div>
                    </div>
                    <TurnAnswer loading={t.loading} error={t.error} response={t.response} elapsed={elapsed} onOpenEvidence={open}
                      onClarifySubmit={onClarifySubmit} onExportReport={id => void onExportReport(id)} clarifyActive={idx === thread.length - 1} busy={asking} />
                  </section>
                ))}
                <div ref={endRef} />
              </div>
            </div>
          </div>
          <div className="shrink-0 border-t border-white/[0.06] bg-[#0A0E14]/95 px-3 py-3 backdrop-blur-xl sm:px-6">
            <div className="mx-auto max-w-[900px]">
              <Composer value={question} onChange={setQuestion} onSubmit={() => void onAsk()} asking={asking} disabled={docs.length === 0} placeholder={placeholder} />
              {docs.length === 0 ? <div className="mt-1.5 text-[11px] text-amber-300">{noDocsHint}</div> : null}
            </div>
          </div>
        </main>
      </div>
      <EvidenceDrawer evidence={evidence} renderUrl={evUrl} onClose={closeEv} />
    </div>
  )
}
