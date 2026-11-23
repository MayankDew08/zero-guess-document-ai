import { FileQuestion, ShieldAlert } from 'lucide-react'
import { SectionLabel } from './ui'

/** Explicit refusal to guess. Shows the backend's abstention text and exactly what evidence was missing. */
export function AbstentionCard({ message, missingEvidence }: { message: string; missingEvidence: string[] }) {
  return (
    <section className="rounded-xl border-l-2 border-amber-400 bg-[#161D27] px-4 py-4" role="note" aria-label="Abstained">
      <div className="flex items-start gap-3">
        <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-amber-400/10 text-amber-300"><ShieldAlert aria-hidden="true" size={17} strokeWidth={1.75} /></div>
        <div>
          <h3 className="text-sm font-semibold text-zinc-100">Abstained — no guess made</h3>
          <p className="mt-1 text-[13px] leading-5 text-zinc-300">{message || 'I don’t have proof in the provided documents to answer this question.'}</p>
        </div>
      </div>
      {missingEvidence.length ? (
        <div className="mt-4 border-t border-white/[0.06] pt-3">
          <SectionLabel className="text-amber-200/70">Missing / unverified evidence</SectionLabel>
          <ul className="mt-2 space-y-2">
            {missingEvidence.map((m, i) => <li key={i} className="flex gap-2 text-xs leading-5 text-zinc-400"><FileQuestion aria-hidden="true" size={14} className="mt-0.5 shrink-0 text-amber-300/70" />{m}</li>)}
          </ul>
        </div>
      ) : null}
    </section>
  )
}
