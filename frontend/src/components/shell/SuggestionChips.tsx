export type Suggestion = { tag: string; question: string }

export function SuggestionChips({ suggestions, disabled, onSelect }: { suggestions: Suggestion[]; disabled: boolean; onSelect: (question: string) => void }) {
  return (
    <div>
      <p className="mb-2 text-[10px] font-semibold uppercase tracking-[0.12em] text-zinc-600">Try an auditable question</p>
      <div className="flex flex-wrap justify-center gap-2">
        {suggestions.map((s, i) => (
          <button key={s.tag} type="button" disabled={disabled} onClick={() => onSelect(s.question)} title={s.question}
            className="rounded-full bg-[#161D27] px-3 py-2 text-left text-[11px] text-zinc-400 transition-colors hover:bg-sky-400/10 hover:text-sky-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-500/40 disabled:cursor-not-allowed disabled:opacity-40">
            <span className="mr-1.5 font-mono text-sky-400">{i + 1}</span>{s.tag}
          </button>
        ))}
      </div>
    </div>
  )
}
