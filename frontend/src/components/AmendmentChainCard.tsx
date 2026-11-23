import { useEffect, useRef, useState } from 'react'
import { ChevronRight } from 'lucide-react'
import type { AmendmentChain } from '../types'
import { Badge, Chip, SectionLabel, type Tone } from './ui'
import { QuoteButton, RefChip } from './CitationChip'
import type { AmendmentEdge, OpenEvidence } from './evidence'

function edgeRef(e: AmendmentEdge) {
  // The amending (newer) document carries the evidence sentence.
  return { doc_id: e.from_doc_id, doc_name: e.from_doc_name, page: e.evidence_page, sentence_id: e.evidence_sentence_id ?? null, quote: e.evidence_quote }
}

function EdgeEvidence({ edge, onOpenEvidence }: { edge: AmendmentEdge; onOpenEvidence: OpenEvidence }) {
  return (
    <div className="rounded-lg bg-[#161D27] px-3 py-2.5">
      <div className="mb-2 text-[11px] text-zinc-400">
        <span className="text-zinc-200">{edge.from_doc_name}</span> <b className="font-mono text-sky-300">{edge.relation}</b> <span className="text-zinc-200">{edge.to_doc_name}</span>
        {edge.effective_date ? <> · effective {edge.effective_date}</> : null}
      </div>
      <QuoteButton evidenceRef={edgeRef(edge)} onOpenEvidence={onOpenEvidence} />
      <div className="mt-2 flex flex-wrap items-center gap-2">
        <RefChip evidenceRef={edgeRef(edge)} onOpenEvidence={onOpenEvidence} compact />
        {edge.old_value && edge.new_value ? (
          <span className="font-mono text-[11px] text-zinc-400"><span className="text-zinc-500 line-through">{edge.old_value}</span><span className="mx-2 text-zinc-600">→</span><span className="text-emerald-300">{edge.new_value}</span></span>
        ) : null}
      </div>
    </div>
  )
}

/** Timeline oldest → newest (doc_ids_ordered). Edges point NEWER (from) → OLDER (to). */
export function AmendmentChainCard({ chain, onOpenEvidence }: { chain: AmendmentChain; onOpenEvidence: OpenEvidence }) {
  const [openEdge, setOpenEdge] = useState<string | null>(null)
  const evRef = useRef<HTMLDivElement>(null)
  useEffect(() => { if (openEdge) evRef.current?.scrollIntoView({ block: 'nearest', behavior: 'smooth' }) }, [openEdge])
  const ids = chain.doc_ids_ordered
  const names = chain.doc_names_ordered?.length ? chain.doc_names_ordered : ids
  const edges = chain.edges as AmendmentEdge[]
  const tone: Tone = chain.status === 'resolved' ? 'emerald' : chain.status === 'ambiguous' ? 'amber' : 'rose'
  const edgeBetween = (i: number) => edges.find(e => e.from_doc_id === ids[i + 1] && e.to_doc_id === ids[i])
  const shown = new Set(ids.slice(0, -1).map((_, i) => edgeBetween(i)?.edge_id))
  const extra = edges.filter(e => !shown.has(e.edge_id))
  const expanded = edges.find(e => e.edge_id === openEdge)
  return (
    <article className="rounded-xl bg-[#10151D] px-3.5 py-3.5 sm:px-4">
      <header className="flex flex-wrap items-center gap-2">
        <h4 className="mr-auto text-sm font-semibold text-zinc-100">{chain.subject}</h4>
        <Badge tone={tone}>{chain.status}</Badge>
        <Chip tone="zinc">oldest → newest</Chip>
      </header>
      <div className="mt-4 overflow-x-auto pb-2">
        <div className="flex min-w-max items-center gap-1">
          {ids.map((id, i) => {
            const active = id === chain.active_doc_id
            const edge = i < ids.length - 1 ? edgeBetween(i) : undefined
            return (
              <div key={id} className="flex items-center gap-1">
                <div className={`w-[168px] rounded-lg bg-[#161D27] px-3 py-2.5 ${active ? 'ring-1 ring-emerald-400/50' : ''}`}>
                  <span className={`block truncate text-[11px] font-medium ${active ? 'text-emerald-200' : 'text-zinc-400'}`} title={names[i] ?? id}>{names[i] ?? id}</span>
                  <div className="mt-1.5 h-4">{active ? <Badge tone="emerald" className="px-1.5 py-0.5 text-[9px]">✓ ACTIVE</Badge> : null}</div>
                </div>
                {i < ids.length - 1 ? (
                  <div className="flex w-[132px] flex-col items-center">
                    {edge ? (
                      <button type="button" aria-expanded={openEdge === edge.edge_id} onClick={() => setOpenEdge(o => (o === edge.edge_id ? null : edge.edge_id))}
                        className="flex w-full flex-col items-center gap-0.5 rounded-md px-1 py-1 text-center hover:bg-white/[0.05] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-500/40">
                        <span className="font-mono text-[9px] font-semibold text-sky-300">{edge.relation}</span>
                        <span className="font-mono text-[9px] text-zinc-500">{edge.effective_date ? `eff. ${edge.effective_date}` : 'date unknown'}</span>
                        <span className="flex w-full items-center"><span className="h-px flex-1 bg-white/10" /><ChevronRight aria-hidden="true" size={12} className={`text-zinc-500 transition-transform ${openEdge === edge.edge_id ? 'rotate-90' : ''}`} /></span>
                      </button>
                    ) : <span className="h-px w-full bg-white/10" />}
                  </div>
                ) : null}
              </div>
            )
          })}
        </div>
      </div>
      {expanded ? <div ref={evRef} className="mt-2 scroll-mb-4"><EdgeEvidence edge={expanded} onOpenEvidence={onOpenEvidence} /></div> : null}
      {extra.length ? (
        <div className="mt-2 space-y-2">
          <SectionLabel>Other lineage edges</SectionLabel>
          {extra.map(e => <EdgeEvidence key={e.edge_id} edge={e} onOpenEvidence={onOpenEvidence} />)}
        </div>
      ) : null}
      {chain.active_rule ? (
        <div className="mt-3 rounded-lg bg-emerald-400/[0.07] px-3.5 py-3">
          <SectionLabel className="text-emerald-400/80">Active rule · {chain.active_doc_name}</SectionLabel>
          <p className="mt-1.5 text-[13px] leading-5 text-emerald-100">{chain.active_rule}</p>
        </div>
      ) : null}
    </article>
  )
}
