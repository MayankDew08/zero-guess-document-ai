import { AlertTriangle, Info, ShieldAlert, ShieldCheck, XCircle } from 'lucide-react'
import type { AskResponse } from '../types'
import { Badge, MetricTile, SectionLabel, type Tone } from './ui'
import { CitationChip } from './CitationChip'
import { ClaimCard } from './ClaimCard'
import { BlockedClaims } from './BlockedClaims'
import { ContradictionCard } from './ContradictionCard'
import { AmendmentChainCard } from './AmendmentChainCard'
import { AbstentionCard } from './AbstentionCard'
import { CalculationCard } from './CalculationCard'
import { ClarifyCard } from './ClarifyCard'
import { TraceCard } from './TraceCard'
import { LoadingCard, PipelineRunCard } from './LoadingCard'
import type { ClientStage } from './stages'
import type { OpenEvidence } from './evidence'

export type { EvidenceRef, OpenEvidence } from './evidence'

export function StatusBadge({ status }: { status: AskResponse['status'] }) {
  const m = {
    answered: { label: 'Verified answer', tone: 'emerald' as Tone, Icon: ShieldCheck },
    partially_answered: { label: 'Partially supported', tone: 'amber' as Tone, Icon: Info },
    contradicted: { label: 'Conflicting evidence', tone: 'rose' as Tone, Icon: AlertTriangle },
    abstained: { label: 'Safe abstention', tone: 'zinc' as Tone, Icon: ShieldAlert },
  }[status]
  return <Badge tone={m.tone} className="px-2.5 py-1.5 text-xs"><m.Icon aria-hidden="true" size={14} strokeWidth={1.75} />{m.label}</Badge>
}

const pct = (v: number) => `${Math.round(v * 100)}%`

export function AnswerBlock({ response: r, stages, onOpenEvidence, onClarifySubmit, onExportReport, clarifyActive, busy }: {
  response: AskResponse
  stages: ClientStage[]
  onOpenEvidence: OpenEvidence
  onClarifySubmit: (baseQuestion: string, values: Record<string, string>) => void
  onExportReport: (requestId: string) => void
  clarifyActive: boolean
  busy: boolean
}) {
  const abstained = r.status === 'abstained'
  const faithTone: Tone = r.faithfulness_pct == null ? 'zinc' : r.faithfulness_pct === 100 ? 'emerald' : r.faithfulness_pct >= 50 ? 'amber' : 'rose'
  const drafted = r.drafted_claims_count ?? 0
  const blockedSub = drafted > 0 ? `draft support ${r.draft_support_pct == null ? 'N/A' : `${r.draft_support_pct}%`} · ${drafted} drafted` : 'no claims drafted'
  const conf = r.confidence
  const confTone: Tone = conf == null ? 'zinc' : conf >= 0.7 ? 'emerald' : conf >= 0.4 ? 'amber' : 'rose'
  // One chip per distinct cited sentence (several claims often share a sentence; also keeps React keys unique).
  const cites = [...new Map(r.claims.flatMap(c => c.citations).map(c => [c.sentence_id, c])).values()]
  // When the only thing missing is calculation input, the clarify form is the answer — not a refusal.
  const showAbstain = abstained && !r.clarification_needed
  return (
    <article className="overflow-hidden rounded-xl bg-[#10151D] ring-1 ring-inset ring-white/[0.07]">
      <header className="flex flex-col gap-3 border-b border-white/[0.06] px-4 py-3.5 sm:px-5">
        <div className="flex flex-wrap items-center gap-2">
          <StatusBadge status={r.status} />
          <Badge tone="zinc">{r.workspace === 'byo_private' ? 'BYO private' : 'Bank official'}</Badge>
          <span className="ml-auto font-mono text-[10px] tabular-nums text-zinc-600" title="request id">{r.request_id}</span>
          <button type="button" onClick={() => onExportReport(r.request_id)} className="rounded-md px-2 py-1.5 text-[11px] text-zinc-400 transition hover:bg-white/[0.06] hover:text-zinc-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-500/40">Export report</button>
        </div>
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
          <MetricTile prominent label="Faithfulness" tone={faithTone} value={r.faithfulness_pct == null ? 'N/A' : `${r.faithfulness_pct}%`}
            sub={r.total_shown_sentences > 0 ? `${r.verified_sentences_count}/${r.total_shown_sentences} sentences verified` : 'no sentences shown'} />
          <MetricTile prominent label="Blocked claims" tone={r.blocked_claims_count > 0 ? 'rose' : 'emerald'} value={String(r.blocked_claims_count)} sub={blockedSub} />
          <MetricTile label="Confidence" tone={confTone} value={conf == null ? 'N/A' : pct(conf)} sub="heuristic · not proof">
            {r.confidence_breakdown ? (
              <details className="group mt-1.5">
                <summary className="cursor-pointer list-none text-[10px] text-sky-300 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-500/40">Breakdown <span aria-hidden="true" className="inline-block text-zinc-500 group-open:rotate-180">⌄</span></summary>
                <div className="mt-2 space-y-1.5">
                  {Object.entries(r.confidence_breakdown).map(([k, v]) => (
                    <div key={k}>
                      <div className="mb-0.5 flex justify-between text-[9px] text-zinc-500"><span>{k.replace(/_/g, ' ')}</span><span className="font-mono tabular-nums">{pct(v)}</span></div>
                      <div className="h-1 rounded-full bg-white/[0.06]"><div className={`h-1 rounded-full ${k.includes('penalty') ? 'bg-rose-400/70' : 'bg-sky-400/70'}`} style={{ width: `${Math.min(100, Math.max(0, v * 100))}%` }} /></div>
                    </div>
                  ))}
                </div>
              </details>
            ) : null}
          </MetricTile>
        </div>
      </header>

      <div className="space-y-4 px-4 py-4 sm:px-5">
        {r.status === 'contradicted' ? (
          <div className="flex items-start gap-2 rounded-lg bg-rose-400/[0.07] px-3 py-2.5 text-xs leading-5 text-rose-200"><AlertTriangle aria-hidden="true" size={14} className="mt-0.5 shrink-0" />Conflicting sources detected — not resolved by guessing. See contradiction alerts below.</div>
        ) : null}
        {r.status === 'partially_answered' ? (
          <div className="rounded-lg bg-amber-400/[0.07] px-3 py-2.5 text-xs leading-5 text-amber-200">
            <div className="flex items-start gap-2"><Info aria-hidden="true" size={14} className="mt-0.5 shrink-0" />Only part of this question is proven by the documents. The rest is withheld, not guessed.</div>
            {r.missing_evidence.length ? <ul className="ml-6 mt-1.5 list-disc space-y-0.5 text-amber-200/90">{r.missing_evidence.map((m, i) => <li key={i}>{m}</li>)}</ul> : null}
          </div>
        ) : null}

        {showAbstain ? <AbstentionCard message={r.answer} missingEvidence={r.missing_evidence} /> : r.answer ? <p className="whitespace-pre-wrap text-[15px] leading-7 text-zinc-200">{r.answer}</p> : null}
        {!abstained && cites.length > 0 ? <div className="flex flex-wrap gap-1.5" aria-label="Citations">{cites.map(c => <CitationChip key={c.sentence_id} citation={c} onOpenEvidence={onOpenEvidence} compact />)}</div> : null}
        {r.clarification_needed ? <ClarifyCard clarification={r.clarification_needed} active={clarifyActive} busy={busy} onSubmit={onClarifySubmit} /> : null}

        {r.calculation ? <section><SectionLabel className="mb-2">Calculation</SectionLabel><CalculationCard calculation={r.calculation} onOpenEvidence={onOpenEvidence} /></section> : null}
        {r.contradictions.length ? <section className="space-y-2"><SectionLabel>Contradiction alerts · {r.contradictions.length}</SectionLabel>{r.contradictions.map(c => <ContradictionCard key={c.contradiction_id} contradiction={c} onOpenEvidence={onOpenEvidence} />)}</section> : null}
        {r.amendment_chains.length ? <section className="space-y-2"><SectionLabel>Amendment chains · {r.amendment_chains.length}</SectionLabel>{r.amendment_chains.map(c => <AmendmentChainCard key={c.chain_id} chain={c} onOpenEvidence={onOpenEvidence} />)}</section> : null}
        {r.claims.length ? <section className="space-y-2"><SectionLabel>Verified claims · {r.claims.length}</SectionLabel>{r.claims.map(c => <ClaimCard key={c.claim_id} claim={c} onOpenEvidence={onOpenEvidence} />)}</section> : null}
        {r.blocked_claims.length ? <BlockedClaims claims={r.blocked_claims} onOpenEvidence={onOpenEvidence} /> : null}
        {r.pipeline_trace ? <TraceCard trace={r.pipeline_trace} /> : null}
        {stages.length ? <PipelineRunCard stages={stages} /> : null}
      </div>
    </article>
  )
}

/** One conversation turn's answer slot: loading → error → response. */
export function TurnAnswer({ loading, error, response, elapsed, stages, ...rest }: {
  loading: boolean; error?: string; response?: AskResponse; elapsed: number; stages: ClientStage[]
  onOpenEvidence: OpenEvidence
  onClarifySubmit: (baseQuestion: string, values: Record<string, string>) => void
  onExportReport: (requestId: string) => void
  clarifyActive: boolean; busy: boolean
}) {
  if (loading) return <LoadingCard elapsedSeconds={elapsed} stages={stages} />
  if (error) return <div role="alert" className="flex items-start gap-2 rounded-xl bg-rose-400/[0.07] px-4 py-3 text-sm text-rose-200 ring-1 ring-inset ring-rose-400/20"><XCircle aria-hidden="true" size={15} className="mt-0.5 shrink-0" /><span className="min-w-0 break-words">{error}</span></div>
  if (!response) return null
  return <AnswerBlock response={response} stages={stages} {...rest} />
}
