import { useEffect, useRef, useState } from 'react'
import type { AskResponse, Calculation, Citation, Claim } from './types'
import { ask, createReport, getDocuments, ingestFiles, ingestSamples, renderUrl, reportDownloadUrl } from './api/client'

const PRESETS: { label: string; tag: string; question: string }[] = [
  { tag: 'Active Rule (Amendment Chain)', label: 'Active Rule', question: 'What is the late payment fee according to the latest active rule?' },
  { tag: 'Contradiction Alert', label: 'Contradiction', question: 'Are there any conflicting rules on late payment fees or grace periods?' },
  { tag: 'Multi-Page & Fee Table', label: 'Fee Table', question: 'What are the processing fees, bounce charges, and borrower eligibility conditions in the latest policy?' },
  { tag: 'Calculation with Working', label: 'Calculation', question: 'Calculate the late payment penalty on an overdue EMI of Rs 50,000 for 2 months under the latest active rule.' },
  { tag: 'Hindi Q&A', label: 'हिन्दी', question: 'नवीनतम सक्रिय नियम के अनुसार विलंब भुगतान शुल्क (late payment fee) क्या है?' },
  { tag: 'Zero-Guessing Abstention', label: 'Abstention', question: 'What is the policy on cryptocurrency collateral for personal loans?' },
]

function Spinner({ label, seconds }: { label: string; seconds: number }) {
  return (
    <div role="status" className="flex items-center gap-3 border border-sky-900/60 bg-sky-950/30 rounded-xl p-4 text-sm text-sky-200">
      <span className="inline-block h-5 w-5 rounded-full border-2 border-sky-400 border-t-transparent animate-spin" />
      <div>
        <div className="font-medium">{label}</div>
        <div className="text-xs text-sky-300/70">Retrieve → rerank → draft → verify every claim · {seconds}s elapsed (first query loads models)</div>
      </div>
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
  return <span className={`px-2 py-0.5 rounded border text-xs ${colors[status] || 'bg-slate-700 text-slate-200 border-slate-600'}`}>{status}</span>
}

type EvidenceRef = { doc_id: string; doc_name: string; page: number; sentence_id?: string | null; quote: string; nli_label?: string | null }

function CitationChip({ c, onOpen }: { c: EvidenceRef; onOpen: (c: EvidenceRef) => void }) {
  return (
    <button onClick={() => onOpen(c)} title="Open PDF evidence preview"
      className="inline-flex items-center gap-1 text-[11px] px-2 py-0.5 rounded-full bg-sky-900/50 hover:bg-sky-800/70 text-sky-200 border border-sky-800 cursor-pointer">
      📄 {c.doc_name} p.{c.page}
    </button>
  )
}

function EvidenceModal({ ev, onClose }: { ev: EvidenceRef; onClose: () => void }) {
  const [imgState, setImgState] = useState<'loading' | 'ok' | 'error'>('loading')
  useEffect(() => {
    const h = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', h)
    return () => window.removeEventListener('keydown', h)
  }, [onClose])
  return (
    <div className="fixed inset-0 z-50 bg-black/70 flex items-center justify-center p-4" onClick={onClose} role="dialog" aria-modal="true">
      <div className="bg-slate-900 border border-slate-700 rounded-xl max-w-5xl w-full max-h-[92vh] overflow-hidden flex flex-col" onClick={e => e.stopPropagation()}>
        <div className="flex items-center justify-between px-4 py-3 border-b border-slate-800">
          <div className="text-sm"><span className="font-semibold">PDF Evidence Preview</span> <span className="text-slate-400">· {ev.doc_name} · page {ev.page}</span></div>
          <button onClick={onClose} className="px-2 py-1 text-sm rounded bg-slate-800 hover:bg-slate-700">Close ✕</button>
        </div>
        <div className="grid md:grid-cols-5 gap-4 p-4 overflow-auto">
          <div className="md:col-span-3 border border-slate-700 rounded bg-white min-h-40 relative">
            {imgState === 'loading' && <div className="absolute inset-0 flex items-center justify-center text-slate-500 text-sm">Rendering page…</div>}
            {imgState === 'error' && <div className="p-4 text-red-600 text-sm">Could not render this page.</div>}
            <img src={renderUrl(ev.doc_id, ev.page, ev.sentence_id || undefined)} alt={`${ev.doc_name} page ${ev.page} with highlighted evidence`}
              className="w-full block" onLoad={() => setImgState('ok')} onError={() => setImgState('error')} />
          </div>
          <div className="md:col-span-2 space-y-3">
            <div>
              <div className="text-xs uppercase tracking-wide text-slate-500 mb-1">Verbatim quote (resolved by backend)</div>
              <blockquote className="border-l-4 border-amber-400 bg-amber-300/10 text-slate-100 text-sm p-3 rounded-r">“{ev.quote}”</blockquote>
            </div>
            <div className="text-xs text-slate-400">Source: <span className="text-slate-200">{ev.doc_name}</span>, page {ev.page}{ev.sentence_id && <> · <code>{ev.sentence_id}</code></>}</div>
            {ev.nli_label && <div className="text-xs text-slate-400">NLI verdict: <span className="text-slate-200">{ev.nli_label}</span></div>}
            <div className="text-xs text-slate-500">The highlighted region on the page is the exact cited passage.</div>
          </div>
        </div>
      </div>
    </div>
  )
}

function ClaimCard({ claim, onOpen }: { claim: Claim; onOpen: (c: EvidenceRef) => void }) {
  const blocked = claim.status === 'blocked'
  return (
    <div className={`border rounded-lg p-3 ${blocked ? 'border-amber-900/60 bg-amber-950/10' : 'border-slate-800 bg-slate-900/60'}`}>
      <div className="flex items-start justify-between gap-3">
        <p className={`text-sm ${blocked ? 'text-slate-400 line-through decoration-amber-700/60' : 'text-slate-100'}`}>{claim.text}</p>
        <StatusBadge status={claim.status} />
      </div>
      {claim.reason && <p className="text-xs text-amber-300 mt-2">Blocked: {claim.reason}</p>}
      <div className="mt-2 flex flex-wrap gap-1">
        {claim.citations.map((c: Citation, i: number) => <CitationChip key={i} c={c} onOpen={onOpen} />)}
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
          <div key={k} className="bg-slate-950/60 border border-slate-800 rounded p-2">
            <div className="text-[10px] uppercase text-slate-500">{k.replace(/_/g, ' ')}</div>
            <div className="text-sm text-slate-100">{String(v)}</div>
          </div>
        ))}
      </div>
      <ol className="list-decimal ml-5 text-sm text-slate-200 space-y-1">{calc.steps.map((s, i) => <li key={i}>{s}</li>)}</ol>
      <div className="mt-3 text-lg font-semibold text-emerald-300">Result: {calc.result}</div>
      {calc.citation && <div className="mt-2 flex flex-wrap items-center gap-2 text-xs text-slate-400">Rate taken from: <CitationChip c={calc.citation} onOpen={onOpen} /><span className="italic">“{calc.citation.quote}”</span></div>}
      {calc.warnings.map((w, i) => <div key={i} className="mt-2 text-xs text-amber-300 border border-amber-900/50 bg-amber-950/20 rounded p-2">⚠ {w}</div>)}
    </div>
  )
}

export default function App() {
  const [docs, setDocs] = useState<any[]>([])
  const [files, setFiles] = useState<File[]>([])
  const [question, setQuestion] = useState(PRESETS[0].question)
  const [answer, setAnswer] = useState<AskResponse | null>(null)
  const [asking, setAsking] = useState(false)
  const [busy, setBusy] = useState(false)
  const [elapsed, setElapsed] = useState(0)
  const [error, setError] = useState<string | null>(null)
  const [reportUrl, setReportUrl] = useState<string | null>(null)
  const [evidence, setEvidence] = useState<EvidenceRef | null>(null)
  const timer = useRef<number | null>(null)

  useEffect(() => { void refreshDocs() }, [])

  async function refreshDocs() {
    try { setDocs((await getDocuments()).documents || []) } catch { /* backend may be offline */ }
  }

  async function onIngest() {
    setError(null); setBusy(true)
    try { await ingestFiles(files); await refreshDocs(); setFiles([]) }
    catch (e: any) { setError(e.message || String(e)) }
    finally { setBusy(false) }
  }

  async function onLoadSamples() {
    setError(null); setBusy(true)
    try { await ingestSamples(); await refreshDocs() }
    catch (e: any) { setError(e.message || String(e)) }
    finally { setBusy(false) }
  }

  async function onAsk(q: string = question) {
    if (!q.trim() || asking) return
    setError(null); setAsking(true); setReportUrl(null); setElapsed(0)
    timer.current = window.setInterval(() => setElapsed(s => s + 1), 1000)
    try { setAnswer(await ask(q, false)) }
    catch (e: any) { setError(e.message || String(e)) }
    finally { setAsking(false); if (timer.current) window.clearInterval(timer.current) }
  }

  function runPreset(q: string) { setQuestion(q); void onAsk(q) }

  async function onReport() {
    if (!answer) return
    setError(null)
    try {
      const rep = await createReport(answer)
      setReportUrl(reportDownloadUrl(rep.report_id))
      window.open(reportDownloadUrl(rep.report_id), '_blank')
    } catch (e: any) { setError(e.message || String(e)) }
  }

  const open = (c: EvidenceRef) => setEvidence(c)

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100">
      {evidence && <EvidenceModal ev={evidence} onClose={() => setEvidence(null)} />}
      <div className="max-w-7xl mx-auto p-6">
        <header className="mb-6">
          <h1 className="text-3xl font-bold tracking-tight">Zero-Guessing Document AI</h1>
          <p className="text-slate-400 mt-1">Verifiable multi-PDF Q&A with citations, contradiction checks, amendment chains, and abstention. 100% local open-source models.</p>
        </header>

        {error && <div className="mb-4 p-3 rounded border border-red-800 bg-red-950/40 text-red-200 text-sm">{error}</div>}

        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          <section className="lg:col-span-1 space-y-4">
            <div className="border border-slate-800 rounded-xl p-4 bg-slate-900/40">
              <h2 className="font-semibold mb-3">Documents</h2>
              <input type="file" multiple accept=".pdf" onChange={e => setFiles(Array.from(e.target.files || []))} className="block w-full text-sm text-slate-300 file:mr-3 file:py-1.5 file:px-3 file:rounded file:border-0 file:bg-slate-800 file:text-slate-100" />
              <div className="flex gap-2 mt-3">
                <button onClick={onIngest} disabled={busy || files.length === 0} className="px-3 py-1.5 rounded bg-sky-600 hover:bg-sky-500 disabled:opacity-50 text-sm">Ingest</button>
                <button onClick={onLoadSamples} disabled={busy} className="px-3 py-1.5 rounded bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 text-sm">{busy ? 'Indexing…' : 'Load Demo Sample PDFs'}</button>
              </div>
              <div className="mt-4 space-y-1">
                {docs.length === 0 ? <p className="text-xs text-slate-500">No documents indexed yet.</p> : docs.map((d: any) => (
                  <div key={d.doc_id} className="text-xs text-slate-300 flex justify-between border-b border-slate-800/60 py-1">
                    <span>{d.doc_name}</span><span className="text-slate-500">{d.num_pages} pg · {d.chunks_created} chunks</span>
                  </div>
                ))}
              </div>
            </div>

            <div className="border border-slate-800 rounded-xl p-4 bg-slate-900/40">
              <h2 className="font-semibold mb-3">Demo Queries</h2>
              <div className="grid grid-cols-2 gap-2">
                {PRESETS.map((p, i) => (
                  <button key={i} onClick={() => runPreset(p.question)} disabled={asking} title={p.question}
                    className="text-left px-2.5 py-2 rounded-lg border border-slate-700 bg-slate-950/60 hover:border-sky-600 hover:bg-slate-900 disabled:opacity-50 text-xs">
                    <div className="text-[10px] text-sky-400">#{i + 1}</div>
                    <div className="font-medium text-slate-100">{p.tag}</div>
                  </button>
                ))}
              </div>
            </div>

            <div className="border border-slate-800 rounded-xl p-4 bg-slate-900/40">
              <h2 className="font-semibold mb-3">Ask</h2>
              <textarea value={question} onChange={e => setQuestion(e.target.value)} rows={4} className="w-full rounded bg-slate-950 border border-slate-700 p-2 text-sm" placeholder="Ask a question about the indexed documents..." />
              <div className="flex gap-2 mt-3">
                <button onClick={() => onAsk()} disabled={asking || !question.trim()} className="px-3 py-1.5 rounded bg-emerald-600 hover:bg-emerald-500 disabled:opacity-50 text-sm">{asking ? 'Verifying…' : 'Ask'}</button>
                <button onClick={onReport} disabled={!answer} className="px-3 py-1.5 rounded bg-slate-700 hover:bg-slate-600 disabled:opacity-50 text-sm">Download Report</button>
              </div>
              {reportUrl && <a href={reportUrl} target="_blank" rel="noreferrer" className="text-xs text-sky-400 mt-2 inline-block">Open report</a>}
            </div>
          </section>

          <section className="lg:col-span-2 space-y-4">
            {asking && <Spinner label="Reading the documents and verifying every claim…" seconds={elapsed} />}
            {!answer && !asking && <div className="border border-slate-800 rounded-xl p-8 bg-slate-900/20 text-slate-500 text-center">Load the demo PDFs, then click a demo query to see verified claims, citations, contradictions, amendment chains, and abstention.</div>}

            {answer && (
              <div className={`space-y-4 ${asking ? 'opacity-40' : ''}`}>
                <div className="border border-slate-800 rounded-xl p-4 bg-slate-900/40">
                  <div className="flex flex-wrap items-center gap-2 mb-3">
                    <StatusBadge status={answer.status} />
                    <span className="text-xs text-slate-400">Faithfulness: <span className="text-slate-100 font-medium">{answer.faithfulness_pct == null ? 'N/A' : `${answer.faithfulness_pct}%`}</span> ({answer.verified_sentences_count}/{answer.total_shown_sentences} shown claims verified)</span>
                    <span className="text-xs text-slate-400">Blocked: <span className="text-amber-300 font-medium">{answer.blocked_claims_count}</span></span>
                    {answer.draft_support_pct != null && <span className="text-xs text-slate-400">Draft support: <span className="text-slate-100 font-medium">{answer.draft_support_pct}%</span></span>}
                  </div>
                  {answer.status === 'abstained' ? (
                    <div className="p-4 rounded-lg border border-slate-600 bg-slate-950/60">
                      <div className="text-sm font-semibold text-slate-100 mb-1">🛑 Abstained — no guess made</div>
                      <p className="text-sm text-slate-200">{answer.answer}</p>
                    </div>
                  ) : (
                    <>
                      <h2 className="font-semibold mb-2">Answer</h2>
                      <p className="text-sm text-slate-200 whitespace-pre-wrap">{answer.answer}</p>
                    </>
                  )}
                  {answer.missing_evidence.length > 0 && (
                    <div className="mt-3 p-3 rounded bg-amber-950/20 border border-amber-900/40">
                      <div className="text-xs font-semibold text-amber-300 mb-1">Missing / Unverified Evidence</div>
                      <ul className="text-xs text-amber-200 list-disc ml-4">{answer.missing_evidence.map((m, i) => <li key={i}>{m}</li>)}</ul>
                    </div>
                  )}
                </div>

                {answer.calculation && <CalculationCard calc={answer.calculation} onOpen={open} />}

                <div className="border border-slate-800 rounded-xl p-4 bg-slate-900/40">
                  <h2 className="font-semibold mb-3">Verified Claims &amp; Citations</h2>
                  <div className="space-y-3">
                    {answer.confidence != null && (
                      <div className="text-xs text-slate-300 bg-slate-950/50 border border-slate-800 rounded p-2">
                        Confidence: <span className="font-semibold">{(Number(answer.confidence) * 100).toFixed(1)}%</span>
                        {answer.confidence_breakdown && <span className="text-slate-500 ml-2">(retrieval {Number(answer.confidence_breakdown.retrieval || 0).toFixed(2)}, verification {Number(answer.confidence_breakdown.verification || 0).toFixed(2)}, contradiction penalty {Number(answer.confidence_breakdown.contradiction_penalty || 0).toFixed(2)})</span>}
                      </div>
                    )}
                    {answer.claims.length === 0 ? <p className="text-sm text-slate-500">No verified claims to display.</p> : answer.claims.map(c => <ClaimCard key={c.claim_id} claim={c} onOpen={open} />)}
                  </div>
                  {answer.blocked_claims.length > 0 && (
                    <div className="mt-4">
                      <h3 className="text-sm font-semibold text-amber-300 mb-2">Blocked Claims (never shown as answer)</h3>
                      <div className="space-y-2">{answer.blocked_claims.map(c => <ClaimCard key={c.claim_id} claim={c} onOpen={open} />)}</div>
                    </div>
                  )}
                </div>

                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  <div className="border border-slate-800 rounded-xl p-4 bg-slate-900/40">
                    <h2 className="font-semibold mb-3">Contradiction Alerts</h2>
                    {answer.contradictions.length === 0 ? <p className="text-sm text-slate-500">No unresolved contradictions detected.</p> : (
                      <div className="space-y-3">
                        {answer.contradictions.map(c => (
                          <div key={c.contradiction_id} className="border border-red-900/40 bg-red-950/10 rounded p-3 text-xs">
                            <div className="flex items-center gap-2 mb-1"><span className="font-semibold text-red-300">{c.subject}</span><StatusBadge status={c.status} /></div>
                            <p className="text-slate-300 mb-2">{c.explanation}</p>
                            {c.values.map((v: any, i: number) => (
                              <div key={i} className="bg-slate-950/50 p-2 rounded mb-1">
                                <div className="mb-1"><CitationChip c={v} onOpen={open} /></div>
                                <div className="text-slate-200">“{v.quote}”</div>
                              </div>
                            ))}
                          </div>
                        ))}
                      </div>
                    )}
                  </div>

                  <div className="border border-slate-800 rounded-xl p-4 bg-slate-900/40">
                    <h2 className="font-semibold mb-3">Amendment Chains</h2>
                    {answer.amendment_chains.length === 0 ? <p className="text-sm text-slate-500">No amendment chains detected.</p> : (
                      <div className="space-y-3">
                        {answer.amendment_chains.map(ch => (
                          <div key={ch.chain_id} className="border border-indigo-900/40 bg-indigo-950/10 rounded p-3 text-xs">
                            <div className="font-semibold text-indigo-300 mb-1">{ch.subject}</div>
                            <div className="text-slate-300 mb-1">{(ch.doc_names_ordered?.length ? ch.doc_names_ordered : ch.doc_ids_ordered).join(' → ')}</div>
                            <div className="text-slate-400">Active: <span className="text-slate-200">{ch.active_doc_name || 'unknown'}</span> ({ch.status})</div>
                            {ch.edges.map((e: any, i: number) => (
                              <div key={i} className="mt-2 bg-slate-950/50 p-2 rounded">
                                <div className="text-slate-400"><span className="text-slate-200">{e.from_doc_name}</span> {e.relation} <span className="text-slate-200">{e.to_doc_name}</span></div>
                                <div className="text-slate-200">“{e.evidence_quote}”</div>
                                <div className="mt-1"><CitationChip c={{ doc_id: e.from_doc_id, doc_name: e.from_doc_name, page: e.evidence_page, sentence_id: e.evidence_sentence_id, quote: e.evidence_quote }} onOpen={open} /></div>
                              </div>
                            ))}
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                </div>
              </div>
            )}
          </section>
        </div>
      </div>
    </div>
  )
}
