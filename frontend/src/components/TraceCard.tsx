import { ShieldCheck } from 'lucide-react'
import type { PipelineTrace } from '../types'
import { Collapse, type Tone } from './ui'

const dotCls: Record<Tone, string> = { emerald: 'bg-emerald-400', rose: 'bg-rose-400', amber: 'bg-amber-400', zinc: 'bg-zinc-400', sky: 'bg-sky-400' }
const Dot = ({ tone }: { tone: Tone }) => <span className={`h-1.5 w-1.5 shrink-0 rounded-full ${dotCls[tone]}`} />

/** Only real pipeline_trace numbers; collapsed by default. */
export function TraceCard({ trace }: { trace: PipelineTrace }) {
  const g1 = trace.gate1_retrieval, g2 = trace.gate2_citation_resolution, g3 = trace.gate3_nli_and_numeric, g4 = trace.gate4_lineage_and_conflicts
  const gates: { name: string; tone: Tone; lines: string[] }[] = [
    { name: 'Retrieval · CRAG', tone: g1.passed ? 'emerald' : 'amber', lines: [`${g1.hybrid_candidates} hybrid candidates → ${g1.reranked_kept} kept`, `max rerank ${g1.max_rerank_score == null ? 'n/a' : g1.max_rerank_score.toFixed(3)} · threshold ${g1.threshold}`, g1.passed ? 'passed' : 'below threshold'] },
    { name: 'Citation resolution', tone: g2.rejected_invalid_ids > 0 ? 'rose' : 'emerald', lines: [`${g2.drafted_claims} drafted`, `${g2.resolved_citations} resolved to stored sentences`, `${g2.rejected_invalid_ids} invalid ids rejected`] },
    { name: 'NLI + numeric/date', tone: g3.nli_failed + g3.numeric_failed > 0 ? 'amber' : 'emerald', lines: [`NLI ${g3.nli_passed} pass / ${g3.nli_failed} fail`, `numeric ${g3.numeric_passed} pass / ${g3.numeric_failed} fail`] },
    { name: 'Lineage & abstention', tone: g4.abstained || g4.unresolved_contradictions > 0 ? 'amber' : 'emerald', lines: [`${g4.amendment_chains_found} amendment chain(s)`, `${g4.superseded_docs_filtered} superseded doc(s) excluded`, `${g4.unresolved_contradictions} unresolved contradiction(s)`, g4.abstained ? 'abstained' : 'answered'] },
  ]
  return (
    <Collapse title={<span className="text-xs font-medium text-zinc-300">Verification pipeline · 4 gates</span>} className="rounded-lg bg-[#161D27] px-3.5 py-3" icon={ShieldCheck}
      trailing={<span className="mr-1 flex items-center gap-1.5">{gates.map(g => <Dot key={g.name} tone={g.tone} />)}</span>}>
      <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
        {gates.map((g, i) => (
          <div key={g.name} className="rounded-lg bg-[#10151D] px-3 py-2.5">
            <div className="flex items-center gap-2 text-[11px] font-medium text-zinc-300"><span className="font-mono tabular-nums text-zinc-500">G{i + 1}</span><Dot tone={g.tone} />{g.name}</div>
            <div className="mt-2 space-y-0.5 font-mono text-[10px] leading-4 tabular-nums text-zinc-500">{g.lines.map((l, j) => <div key={j}>{l}</div>)}</div>
          </div>
        ))}
      </div>
    </Collapse>
  )
}
