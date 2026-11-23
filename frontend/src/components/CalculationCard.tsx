import { AlertTriangle, Calculator } from 'lucide-react'
import type { Calculation } from '../types'
import { Badge, Chip } from './ui'
import { CitationChip } from './CitationChip'
import type { OpenEvidence } from './evidence'

const label = (k: string) => k.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase())
const fmt = (v: unknown) => (typeof v === 'number' ? new Intl.NumberFormat('en-IN', { maximumFractionDigits: 4 }).format(v) : String(v))

/** Deterministic working: formula, inputs, steps, result — all straight from `calculation`. */
export function CalculationCard({ calculation: c, onOpenEvidence }: { calculation: Calculation; onOpenEvidence: OpenEvidence }) {
  const inputs = Object.entries(c.inputs).filter(([k]) => k !== 'source')
  const source = c.inputs.source
  return (
    <article className="rounded-xl bg-[#10151D] px-3.5 py-3.5 sm:px-4">
      <header className="flex flex-wrap items-center gap-2">
        <Calculator aria-hidden="true" size={16} className="text-sky-300" />
        <h4 className="text-sm font-semibold text-zinc-100">Calculation working</h4>
        <Badge tone="sky" className="ml-auto">deterministic Python math — no LLM arithmetic</Badge>
      </header>
      <div className="mt-3 rounded-lg bg-[#161D27] px-3 py-2.5 font-mono text-[12px] leading-5 text-zinc-300">{c.formula}</div>
      <div className="mt-2.5 flex flex-wrap gap-1.5">
        {inputs.map(([k, v]) => <Chip key={k} tone="zinc" className="font-mono tabular-nums">{label(k)}: {fmt(v)}</Chip>)}
      </div>
      {typeof source === 'string' && source ? <p className="mt-1.5 text-[11px] text-zinc-500">Rate source: {source}</p> : null}
      <ol className="mt-3 space-y-2">
        {c.steps.map((s, i) => (
          <li key={i} className="flex gap-2.5 text-[12px] leading-5 text-zinc-400"><span className="font-mono tabular-nums text-zinc-600">{String(i + 1).padStart(2, '0')}</span><span>{s}</span></li>
        ))}
      </ol>
      <div className="mt-3 flex flex-wrap items-center justify-between gap-2 rounded-lg bg-emerald-400/[0.07] px-3.5 py-3">
        <span className="text-xs text-emerald-200">Result</span>
        <span className="font-mono text-[22px] font-semibold tabular-nums text-emerald-300">{c.result}</span>
      </div>
      {c.citation ? <div className="mt-2.5 flex flex-wrap items-center gap-2 text-[11px] text-zinc-500">Rate taken from <CitationChip citation={c.citation} onOpenEvidence={onOpenEvidence} /></div> : null}
      {c.warnings.map((w, i) => <div key={i} className="mt-2.5 flex items-start gap-2 rounded-lg bg-amber-400/[0.07] px-3 py-2.5 text-xs leading-5 text-amber-200"><AlertTriangle aria-hidden="true" size={14} className="mt-0.5 shrink-0" />{w}</div>)}
    </article>
  )
}
