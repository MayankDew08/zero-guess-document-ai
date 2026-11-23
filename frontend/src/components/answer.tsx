import { useState } from 'react'
import type { AskResponse, Calculation, Citation, Claim, ClarificationNeeded, PipelineTrace } from '../types'

export type EvidenceRef = { doc_id: string; doc_name: string; page: number; sentence_id?: string | null; quote: string; nli_label?: string | null }

export function StatusBadge({ status }: { status: string }) {
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

export function CitationChip({ c, onOpen, active }: { c: EvidenceRef; onOpen: (c: EvidenceRef) => void; active?: boolean }) {
  return (
    <button onClick={() => onOpen(c)} title="Open highlighted PDF evidence"
      className={`inline-flex items-center gap-1 text-[11px] px-2 py-0.5 rounded-full border cursor-pointer ${active ? 'bg-amber-500/20 border-amber-500 text-amber-200' : 'bg-sky-900/50 hover:bg-sky-800/70 text-sky-200 border-sky-800'}`}>
      📄 {c.doc_name} p.{c.page}
    </button>
  )
}

export function Metric({ label, value, tone, sub }: { label: string; value: string; tone?: string; sub?: string }) {
  return (
    <div className="border border-slate-800 bg-slate-900/50 rounded-xl p-3">
      <div className="text-[10px] uppercase tracking-wide text-slate-500">{label}</div>
      <div className={`text-2xl font-semibold ${tone || 'text-slate-100'}`}>{value}</div>
      {sub && <div className="text-[11px] text-slate-500">{sub}</div>}
    </div>
  )
}

export function ClaimCard({ claim, onOpen, activeId }: { claim: Claim; onOpen: (c: EvidenceRef) => void; activeId?: string }) {
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

export function CalculationCard({ calc, onOpen }: { calc: Calculation; onOpen: (c: EvidenceRef) => void }) {
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

export function TraceCard({ t }: { t: PipelineTrace }) {
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


/** Interactive zero-guessing slot form: asks for the inputs only the user can provide; never guesses them. */
export function ClarifyCard({ c, active, busy, onSubmit }: { c: ClarificationNeeded; active: boolean; busy: boolean; onSubmit: (replyText: string) => void }) {
  const [vals, setVals] = useState<Record<string, string>>({})
  const ready = c.missing_fields.every(f => Number(vals[f.key]) > 0)
  const compose = () => {
    const parts: string[] = []
    if (vals.principal) parts.push(`Rs ${Number(vals.principal)}`)
    if (vals.months) parts.push(`${Number(vals.months)} ${Number(vals.months) === 1 ? 'month' : 'months'}`)
    return parts.join(' for ')
  }
  return (
    <form data-testid="clarify-card" className={`border rounded-xl p-4 ${active ? 'border-sky-700 bg-sky-950/30' : 'border-slate-800 bg-slate-900/30 opacity-60'}`}
      onSubmit={e => { e.preventDefault(); if (active && ready && !busy) onSubmit(compose()) }}>
      <div className="text-sm font-semibold text-sky-200 mb-1">🧮 Inputs needed — no guessing</div>
      <p className="text-xs text-slate-300 mb-3">{c.message}</p>
      <div className="grid sm:grid-cols-2 gap-3">
        {c.missing_fields.map(f => (
          <label key={f.key} className="text-xs text-slate-400 block">
            {f.label}
            <input type="number" min="0" step="any" inputMode="decimal" disabled={!active || busy} value={vals[f.key] ?? ''} placeholder={f.placeholder}
              onChange={e => setVals(v => ({ ...v, [f.key]: e.target.value }))}
              className="mt-1 w-full rounded bg-slate-950 border border-slate-700 p-2 text-sm text-slate-100 disabled:opacity-60" />
          </label>
        ))}
      </div>
      <button type="submit" disabled={!active || !ready || busy} className="mt-3 px-4 py-1.5 rounded bg-sky-600 hover:bg-sky-500 disabled:opacity-40 text-sm">Calculate Deterministically</button>
      {!active && <span className="ml-3 text-[11px] text-slate-500">answered in a later turn</span>}
    </form>
  )
}

/** One verified answer: strip, answer, calculation, claims, conflicts, amendment chain, trace. */
export function AnswerBlock({ answer, onOpen, activeSentenceId, collapseDetails }: { answer: AskResponse; onOpen: (c: EvidenceRef) => void; activeSentenceId?: string; collapseDetails?: boolean }) {
  const faith = answer.faithfulness_pct
  const cites = answer.claims.flatMap(c => c.citations)
  return (
    <div className="space-y-3">
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <Metric label="Faithfulness" value={faith == null ? 'N/A' : `${faith}%`} tone={faith === 100 ? 'text-emerald-300' : 'text-amber-300'} sub={`${answer.verified_sentences_count}/${answer.total_shown_sentences} shown claims verified`} />
        <Metric label="Blocked claims" value={String(answer.blocked_claims_count)} tone={answer.blocked_claims_count ? 'text-amber-300' : 'text-slate-100'} sub={(answer.drafted_claims_count ?? 0) > 0 ? `draft support ${answer.draft_support_pct ?? 0}% (${answer.drafted_claims_count} drafted)` : 'no claims drafted'} />
        <Metric label="Confidence" value={answer.confidence == null ? 'N/A' : `${(answer.confidence * 100).toFixed(0)}%`} sub={answer.confidence_breakdown ? `ret ${answer.confidence_breakdown.retrieval?.toFixed(2)} · ver ${answer.confidence_breakdown.verification?.toFixed(2)} · pen ${answer.confidence_breakdown.contradiction_penalty?.toFixed(2)}` : undefined} />
        <Metric label="Status" value={answer.status.replace('_', ' ')} tone={answer.status === 'answered' ? 'text-emerald-300' : answer.status === 'contradicted' ? 'text-red-300' : 'text-amber-300'} />
      </div>

      <div className="border border-slate-800 rounded-xl p-4 bg-slate-900/40">
        {answer.status === 'abstained' ? (
          <div className="p-4 rounded-lg border border-slate-600 bg-slate-950/60"><div className="text-sm font-semibold mb-1">🛑 Abstained — no guess made</div><p className="text-sm text-slate-200">{answer.answer}</p></div>
        ) : (<><h2 className="font-semibold mb-2">Answer</h2><p className="text-sm text-slate-200 whitespace-pre-wrap">{answer.answer}</p></>)}
        {cites.length > 0 && (
          <div className="mt-3 flex flex-wrap gap-1" aria-label="Citations">
            {cites.map((c, i) => <CitationChip key={i} c={c} onOpen={onOpen} active={activeSentenceId === c.sentence_id} />)}
          </div>
        )}
        {answer.missing_evidence.length > 0 && (
          <div className="mt-3 p-3 rounded bg-amber-950/20 border border-amber-900/40">
            <div className="text-xs font-semibold text-amber-300 mb-1">Missing / Unverified Evidence — no proof found for:</div>
            <ul className="text-xs text-amber-200 list-disc ml-4">{answer.missing_evidence.map((m, i) => <li key={i}>{m}</li>)}</ul>
          </div>
        )}
      </div>

      {answer.calculation && <CalculationCard calc={answer.calculation} onOpen={onOpen} />}

      {(answer.claims.length > 0 || answer.blocked_claims.length > 0) && (
        <details open={!collapseDetails} className="border border-slate-800 rounded-xl p-4 bg-slate-900/40">
          <summary className="font-semibold cursor-pointer">Verified Claims &amp; Citations ({answer.claims.length})</summary>
          <div className="space-y-3 mt-3">
            {answer.claims.map(c => <ClaimCard key={c.claim_id} claim={c} onOpen={onOpen} activeId={activeSentenceId} />)}
          </div>
          {answer.blocked_claims.length > 0 && (
            <div className="mt-4"><h3 className="text-sm font-semibold text-amber-300 mb-2">Blocked Claims (never shown as answer)</h3>
              <div className="space-y-2">{answer.blocked_claims.map(c => <ClaimCard key={c.claim_id} claim={c} onOpen={onOpen} />)}</div></div>
          )}
        </details>
      )}

      {answer.contradictions.length > 0 && (
        <div className="border border-red-900/50 rounded-xl p-4 bg-slate-900/40">
          <h2 className="font-semibold mb-3">Contradiction Alerts</h2>
          <div className="space-y-3">
            {answer.contradictions.map(c => (
              <div key={c.contradiction_id} className="border border-red-900/40 bg-red-950/10 rounded p-3 text-xs">
                <div className="flex items-center gap-2 mb-1"><span className="font-semibold text-red-300 capitalize">{c.subject}</span><StatusBadge status={c.status} /></div>
                <p className="text-slate-300 mb-2">{c.explanation}</p>
                <div className="grid md:grid-cols-2 gap-2">
                  {c.values.map((v: any, i: number) => (
                    <div key={i} className="bg-slate-950/60 border border-slate-800 p-2 rounded">
                      <div className="mb-1 flex items-center gap-2"><span className="text-[10px] px-1.5 rounded bg-slate-800 text-slate-400">{i === 0 ? 'A' : 'B'}</span><CitationChip c={v} onOpen={onOpen} active={activeSentenceId === v.sentence_id} /></div>
                      <div className="text-slate-200">“{v.quote}”</div>
                    </div>
                  ))}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {answer.amendment_chains.length > 0 && (
        <div className="border border-slate-800 rounded-xl p-4 bg-slate-900/40">
          <h2 className="font-semibold mb-3">Amendment Chain</h2>
          {answer.amendment_chains.map(ch => {
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
                      <div className="mt-1"><CitationChip c={{ doc_id: e.from_doc_id, doc_name: e.from_doc_name, page: e.evidence_page, sentence_id: e.evidence_sentence_id, quote: e.evidence_quote }} onOpen={onOpen} /></div>
                    </div>
                  ))}
                </div>
              </div>
            )
          })}
        </div>
      )}

      {answer.pipeline_trace && <TraceCard t={answer.pipeline_trace} />}
    </div>
  )
}
