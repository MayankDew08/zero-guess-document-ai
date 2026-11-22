import { useState } from 'react'
import type { AskResponse, Claim } from './types'
import { ask, createReport, getDocuments, ingestFiles, ingestSamples, reportDownloadUrl } from './api/client'

function StatusBadge({ status }: { status: string }) {
  const colors: Record<string, string> = {
    supported: 'bg-emerald-600/30 text-emerald-300 border-emerald-700',
    contradicted: 'bg-red-600/30 text-red-300 border-red-700',
    blocked: 'bg-amber-600/30 text-amber-300 border-amber-700',
    abstained: 'bg-slate-600/30 text-slate-300 border-slate-600',
    answered: 'bg-emerald-600/30 text-emerald-300 border-emerald-700',
    partially_answered: 'bg-amber-600/30 text-amber-300 border-amber-700',
  }
  return <span className={`px-2 py-0.5 rounded border text-xs ${colors[status] || 'bg-slate-700 text-slate-200 border-slate-600'}`}>{status}</span>
}

function ClaimCard({ claim }: { claim: Claim }) {
  return (
    <div className="border border-slate-800 rounded-lg p-3 bg-slate-900/60">
      <div className="flex items-start justify-between gap-3">
        <p className="text-sm text-slate-100">{claim.text}</p>
        <StatusBadge status={claim.status} />
      </div>
      {claim.reason && <p className="text-xs text-amber-300 mt-2">Reason: {claim.reason}</p>}
      <div className="mt-2 space-y-2">
        {claim.citations.map((c, i) => (
          <div key={`${c.sentence_id}-${i}`} className="text-xs bg-slate-950/60 border border-slate-800 rounded p-2">
            <div className="text-slate-300">
              <span className="font-medium">{c.doc_name}</span> · p.{c.page} · <code>{c.sentence_id}</code>
            </div>
            <p className="text-slate-400 mt-1">“{c.quote}”</p>
            {c.nli_label && <div className="text-slate-500 mt-1">NLI: {c.nli_label} {c.nli_scores ? `(ent ${c.nli_scores.entailment?.toFixed(2)})` : ''}</div>}
          </div>
        ))}
      </div>
    </div>
  )
}

export default function App() {
  const [docs, setDocs] = useState<any[]>([])
  const [files, setFiles] = useState<File[]>([])
  const [question, setQuestion] = useState('What is the late payment fee according to the latest active rule?')
  const [answer, setAnswer] = useState<AskResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [reportUrl, setReportUrl] = useState<string | null>(null)

  async function refreshDocs() {
    try {
      const res = await getDocuments()
      setDocs(res.documents || [])
    } catch { /* ignore */ }
  }

  async function onIngest() {
    setError(null); setLoading(true)
    try {
      await ingestFiles(files)
      await refreshDocs()
      setFiles([])
    } catch (e: any) { setError(e.message || String(e)) }
    finally { setLoading(false) }
  }

  async function onLoadSamples() {
    setError(null); setLoading(true)
    try {
      await ingestSamples()
      await refreshDocs()
    } catch (e: any) { setError(e.message || String(e)) }
    finally { setLoading(false) }
  }

  async function onAsk() {
    if (!question.trim()) return
    setError(null); setLoading(true); setReportUrl(null)
    try {
      const res = await ask(question, false)
      setAnswer(res)
    } catch (e: any) { setError(e.message || String(e)) }
    finally { setLoading(false) }
  }

  async function onReport() {
    if (!answer) return
    setError(null)
    try {
      const rep = await createReport(answer)
      setReportUrl(reportDownloadUrl(rep.report_id))
      window.open(reportDownloadUrl(rep.report_id), '_blank')
    } catch (e: any) { setError(e.message || String(e)) }
  }

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100">
      <div className="max-w-7xl mx-auto p-6">
        <header className="mb-6">
          <h1 className="text-3xl font-bold tracking-tight">Zero-Guessing Document AI</h1>
          <p className="text-slate-400 mt-1">Verifiable multi-PDF Q&A with citations, contradiction checks, amendment chains, and abstention.</p>
        </header>

        {error && <div className="mb-4 p-3 rounded border border-red-800 bg-red-950/40 text-red-200 text-sm">{error}</div>}

        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          <section className="lg:col-span-1 space-y-4">
            <div className="border border-slate-800 rounded-xl p-4 bg-slate-900/40">
              <h2 className="font-semibold mb-3">Documents</h2>
              <input type="file" multiple accept=".pdf" onChange={e => setFiles(Array.from(e.target.files || []))} className="block w-full text-sm text-slate-300 file:mr-3 file:py-1.5 file:px-3 file:rounded file:border-0 file:bg-slate-800 file:text-slate-100" />
              <div className="flex gap-2 mt-3">
                <button onClick={onIngest} disabled={loading || files.length === 0} className="px-3 py-1.5 rounded bg-sky-600 hover:bg-sky-500 disabled:opacity-50 text-sm">Ingest</button>
                <button onClick={onLoadSamples} disabled={loading} className="px-3 py-1.5 rounded bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 text-sm">Load Demo Sample PDFs</button>
              </div>
              <div className="mt-4 space-y-1">
                {docs.length === 0 ? <p className="text-xs text-slate-500">No documents indexed yet.</p> : docs.map((d: any) => (
                  <div key={d.doc_id} className="text-xs text-slate-300 flex justify-between border-b border-slate-800/60 py-1">
                    <span>{d.doc_name}</span><span className="text-slate-500">{d.chunks_created} chunks</span>
                  </div>
                ))}
              </div>
            </div>

            <div className="border border-slate-800 rounded-xl p-4 bg-slate-900/40">
              <h2 className="font-semibold mb-3">Ask</h2>
              <textarea value={question} onChange={e => setQuestion(e.target.value)} rows={4} className="w-full rounded bg-slate-950 border border-slate-700 p-2 text-sm" placeholder="Ask a question about the indexed documents..." />
              <div className="flex gap-2 mt-3">
                <button onClick={onAsk} disabled={loading || !question.trim()} className="px-3 py-1.5 rounded bg-emerald-600 hover:bg-emerald-500 disabled:opacity-50 text-sm">{loading ? 'Working...' : 'Ask'}</button>
                <button onClick={onReport} disabled={!answer} className="px-3 py-1.5 rounded bg-slate-700 hover:bg-slate-600 disabled:opacity-50 text-sm">Download Report</button>
              </div>
              {reportUrl && <a href={reportUrl} target="_blank" rel="noreferrer" className="text-xs text-sky-400 mt-2 inline-block">Open report</a>}
            </div>
          </section>

          <section className="lg:col-span-2 space-y-4">
            {!answer && <div className="border border-slate-800 rounded-xl p-8 bg-slate-900/20 text-slate-500 text-center">Ingest documents and ask a question to see verified claims, citations, contradictions, and amendment chains.</div>}

            {answer && (
              <>
                <div className="border border-slate-800 rounded-xl p-4 bg-slate-900/40">
                  <div className="flex flex-wrap items-center gap-2 mb-3">
                    <StatusBadge status={answer.status} />
                    <span className="text-xs text-slate-400">Faithfulness: <span className="text-slate-100 font-medium">{answer.faithfulness_pct == null ? 'N/A' : `${answer.faithfulness_pct}%`}</span> ({answer.verified_sentences_count}/{answer.total_shown_sentences} verified)</span>
                    <span className="text-xs text-slate-400">Blocked: <span className="text-amber-300 font-medium">{answer.blocked_claims_count}</span></span>
                  </div>
                  <h2 className="font-semibold mb-2">Answer</h2>
                  <p className="text-sm text-slate-200 whitespace-pre-wrap">{answer.answer}</p>
                  {answer.missing_evidence.length > 0 && (
                    <div className="mt-3 p-3 rounded bg-amber-950/20 border border-amber-900/40">
                      <div className="text-xs font-semibold text-amber-300 mb-1">Missing / Unverified Evidence</div>
                      <ul className="text-xs text-amber-200 list-disc ml-4">
                        {answer.missing_evidence.map((m, i) => <li key={i}>{m}</li>)}
                      </ul>
                    </div>
                  )}
                </div>

                <div className="border border-slate-800 rounded-xl p-4 bg-slate-900/40">
                  <h2 className="font-semibold mb-3">Verified Claims & Citations</h2>
                  <div className="space-y-3">
                    {answer.claims.length === 0 ? <p className="text-sm text-slate-500">No verified claims to display.</p> : answer.claims.map(c => <ClaimCard key={c.claim_id} claim={c} />)}
                  </div>
                  {answer.blocked_claims.length > 0 && (
                    <div className="mt-4">
                      <h3 className="text-sm font-semibold text-amber-300 mb-2">Blocked Claims</h3>
                      <div className="space-y-2">
                        {answer.blocked_claims.map(c => <ClaimCard key={c.claim_id} claim={c} />)}
                      </div>
                    </div>
                  )}
                </div>

                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  <div className="border border-slate-800 rounded-xl p-4 bg-slate-900/40">
                    <h2 className="font-semibold mb-3">Contradictions</h2>
                    {answer.contradictions.length === 0 ? <p className="text-sm text-slate-500">No contradictions detected.</p> : (
                      <div className="space-y-3">
                        {answer.contradictions.map(c => (
                          <div key={c.contradiction_id} className="border border-red-900/40 bg-red-950/10 rounded p-3 text-xs">
                            <div className="flex items-center gap-2 mb-1"><span className="font-semibold text-red-300">{c.subject}</span><StatusBadge status={c.status} /></div>
                            <p className="text-slate-300 mb-2">{c.explanation}</p>
                            {c.values.map((v: any, i: number) => (
                              <div key={i} className="bg-slate-950/50 p-2 rounded mb-1">
                                <div className="text-slate-400">{v.doc_name} p.{v.page}</div>
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
                            <div className="text-slate-300 mb-1">{ch.doc_ids_ordered.join(' → ')}</div>
                            <div className="text-slate-400">Active: <span className="text-slate-200">{ch.active_doc_name || 'unknown'}</span> ({ch.status})</div>
                            {ch.edges.map((e: any, i: number) => (
                              <div key={i} className="mt-2 bg-slate-950/50 p-2 rounded">
                                <div className="text-slate-400">{e.from_doc_name} {e.relation} {e.to_doc_name}</div>
                                <div className="text-slate-200">“{e.evidence_quote}”</div>
                              </div>
                            ))}
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                </div>
              </>
            )}
          </section>
        </div>
      </div>
    </div>
  )
}
