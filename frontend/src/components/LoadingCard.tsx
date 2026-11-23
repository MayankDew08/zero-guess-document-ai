import { LoaderCircle } from 'lucide-react'

export function LoadingCard({ elapsedSeconds }: { elapsedSeconds: number }) {
  const gates = ['Retrieval', 'Citation resolution', 'NLI + numeric', 'Lineage & conflicts']
  return (
    <section role="status" className="rounded-xl bg-[#10151D] px-4 py-4">
      <div className="flex items-center gap-2 text-sm font-medium text-zinc-200"><LoaderCircle aria-hidden="true" size={16} className="animate-spin text-sky-300" />Verifying locally · <span className="font-mono tabular-nums">{elapsedSeconds}s</span></div>
      <div className="mt-4 grid grid-cols-2 gap-2 sm:grid-cols-4">
        {gates.map((g, i) => <div key={g} className="animate-pulse rounded-lg bg-[#161D27] px-2.5 py-2 text-[10px] text-zinc-500" style={{ animationDelay: `${i * 150}ms` }}>{g}</div>)}
      </div>
      <p className="mt-3 text-[11px] leading-5 text-zinc-600">The first query loads local models, so it can take longer. Every claim is checked before display; no data leaves this machine.</p>
    </section>
  )
}
