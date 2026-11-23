import type { Contradiction } from '../types'
import { Badge, Chip, type Tone } from './ui'
import { QuoteButton, RefChip } from './CitationChip'
import type { ContradictionValue, OpenEvidence } from './evidence'

function refOf(v: ContradictionValue) {
  return { doc_id: v.doc_id, doc_name: v.doc_name, page: v.page, sentence_id: v.sentence_id ?? null, quote: v.quote }
}

function ValuePanel({ value, onOpenEvidence }: { value: ContradictionValue; onOpenEvidence: OpenEvidence }) {
  return (
    <div className="min-w-0 rounded-lg bg-[#161D27] px-3.5 py-3">
      <RefChip evidenceRef={refOf(value)} onOpenEvidence={onOpenEvidence} />
      <div className="mt-3 break-words font-mono text-[24px] font-semibold leading-8 tabular-nums tracking-tight text-rose-200">{value.normalized_value ?? 'Unnormalized'}</div>
      <QuoteButton evidenceRef={refOf(value)} onOpenEvidence={onOpenEvidence} accent="border-rose-400/70" className="mt-2" />
    </div>
  )
}

/** 'possible' = dashed amber (low confidence, never hidden); 'confirmed' = solid rose. */
export function ContradictionCard({ contradiction: c, onOpenEvidence }: { contradiction: Contradiction; onOpenEvidence: OpenEvidence }) {
  const possible = c.status !== 'confirmed'
  const sev: Tone = c.severity === 'high' ? 'rose' : c.severity === 'medium' ? 'amber' : 'zinc'
  const values = c.values as ContradictionValue[]
  const nliScore = (c as Contradiction & { nli_contradiction_score?: number | null }).nli_contradiction_score
  return (
    <article className={`rounded-xl bg-[#10151D] px-3.5 py-3.5 sm:px-4 ${possible ? 'border border-dashed border-amber-400/50' : 'border border-rose-400/60'}`}>
      <header className="flex flex-wrap items-center gap-2">
        <h4 className="mr-auto text-sm font-semibold text-zinc-100">{c.subject}</h4>
        <Chip tone="zinc" className="capitalize">{c.conflict_type}</Chip>
        <Badge tone={sev}>{c.severity} severity</Badge>
        {possible ? <Badge tone="amber" dashed>possible · low confidence</Badge> : <Badge tone="rose">confirmed</Badge>}
      </header>
      <div className={`mt-3 grid grid-cols-1 items-stretch gap-2.5 ${values.length === 2 ? 'sm:grid-cols-[minmax(0,1fr)_auto_minmax(0,1fr)] sm:items-center' : 'sm:grid-cols-2'}`}>
        {values.map((v, i) => (
          <div key={`${v.doc_id}-${v.page}-${v.sentence_id ?? i}`} className="contents">
            {i === 1 ? <div className="hidden rounded-full bg-rose-400/10 px-2 py-1 font-mono text-[10px] font-semibold uppercase tracking-wider text-rose-300 sm:block">vs</div> : null}
            <ValuePanel value={v} onOpenEvidence={onOpenEvidence} />
          </div>
        ))}
      </div>
      <div className="mt-3 flex flex-wrap items-center justify-between gap-2">
        <p className="max-w-2xl text-xs leading-5 text-zinc-400">{c.explanation}</p>
        {nliScore != null ? <span className="font-mono text-[10px] tabular-nums text-zinc-500">NLI contradiction p={nliScore.toFixed(2)}</span> : null}
      </div>
    </article>
  )
}
