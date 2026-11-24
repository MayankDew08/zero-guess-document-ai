import { useEffect, useRef, type KeyboardEvent } from 'react'
import { CornerDownLeft } from 'lucide-react'

export function Composer({ value, onChange, onSubmit, asking, disabled, placeholder }: {
  value: string
  onChange: (v: string) => void
  onSubmit: () => void
  asking: boolean
  /** no documents in this workspace */
  disabled: boolean
  placeholder: string
}) {
  const ref = useRef<HTMLTextAreaElement>(null)
  useEffect(() => {
    const el = ref.current
    if (!el) return
    el.style.height = 'auto'
    el.style.height = `${Math.min(el.scrollHeight, 160)}px`
  }, [value])
  const onKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing && e.keyCode !== 229) { e.preventDefault(); onSubmit() }
  }
  const canSend = !asking && !disabled && value.trim().length > 0
  return (
    <form onSubmit={e => { e.preventDefault(); if (canSend) onSubmit() }} className="rounded-xl bg-[#10151D] p-2.5 ring-1 ring-inset ring-white/[0.08] focus-within:ring-sky-400/30">
      <label htmlFor="question-composer" className="sr-only">Ask a document question</label>
      <div className="flex items-end gap-2">
        <textarea id="question-composer" ref={ref} rows={1} value={value} disabled={disabled} onChange={e => onChange(e.target.value)} onKeyDown={onKeyDown} placeholder={placeholder}
          className="max-h-40 min-h-10 flex-1 resize-none bg-transparent px-2 py-2 text-[13px] leading-5 text-zinc-100 outline-none placeholder:text-zinc-600 disabled:opacity-50" />
        <button type="submit" disabled={!canSend} className="mb-1 inline-flex h-8 shrink-0 items-center gap-2 rounded-lg bg-sky-500 px-3 text-xs font-semibold text-sky-950 transition-colors hover:bg-sky-400 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-300/50 disabled:cursor-not-allowed disabled:opacity-40">
          <span>{asking ? 'Verifying…' : 'Ask'}</span>{!asking ? <CornerDownLeft aria-hidden="true" size={12} className="opacity-70" /> : null}
        </button>
      </div>
    </form>
  )
}
