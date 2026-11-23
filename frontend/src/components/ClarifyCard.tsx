import { useState, type FormEvent } from 'react'
import { CircleHelp } from 'lucide-react'
import type { ClarificationNeeded } from '../types'

/** Zero-guessing slot form: asks only for inputs the user can provide; never guesses them. */
export function ClarifyCard({ clarification, active, busy, onSubmit }: {
  clarification: ClarificationNeeded; active: boolean; busy: boolean
  onSubmit: (baseQuestion: string, values: Record<string, string>) => void
}) {
  const [values, setValues] = useState<Record<string, string>>({})
  const ready = clarification.missing_fields.every(f => Number(values[f.key]) > 0)
  const enabled = active && !busy
  const submit = (e: FormEvent) => { e.preventDefault(); if (enabled && ready) onSubmit(clarification.base_question, values) }
  return (
    <form data-testid="clarify-card" onSubmit={submit} className={`rounded-xl bg-sky-400/[0.07] px-4 py-4 ring-1 ring-inset ring-sky-400/15 ${active ? '' : 'opacity-60'}`}>
      <div className="flex items-start gap-2.5">
        <CircleHelp aria-hidden="true" size={16} className="mt-0.5 shrink-0 text-sky-300" />
        <p className="text-[13px] leading-5 text-sky-100">{clarification.message}</p>
      </div>
      <div className="mt-3 grid gap-3 sm:grid-cols-2">
        {clarification.missing_fields.map(f => (
          <label key={f.key} className="block text-[11px] font-medium text-zinc-300">
            {f.label}
            <input type="number" min="0" step="any" inputMode="decimal" disabled={!enabled} placeholder={f.placeholder} value={values[f.key] ?? ''}
              onChange={e => setValues(v => ({ ...v, [f.key]: e.target.value }))}
              className="mt-1.5 block w-full rounded-lg bg-[#10151D] px-3 py-2.5 text-sm text-zinc-100 outline-none ring-1 ring-inset ring-white/[0.08] placeholder:text-zinc-600 focus-visible:ring-2 focus-visible:ring-sky-500/50 disabled:opacity-60" />
          </label>
        ))}
      </div>
      <div className="mt-3 flex items-center justify-between gap-2">
        <span className="text-[11px] text-zinc-500">{active ? 'No default is assumed.' : 'answered in a later turn'}</span>
        <button type="submit" disabled={!enabled || !ready} className="inline-flex min-h-9 items-center rounded-lg bg-sky-500 px-3.5 text-xs font-semibold text-sky-950 transition-colors hover:bg-sky-400 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-300/50 disabled:cursor-not-allowed disabled:opacity-40">Calculate deterministically</button>
      </div>
    </form>
  )
}
