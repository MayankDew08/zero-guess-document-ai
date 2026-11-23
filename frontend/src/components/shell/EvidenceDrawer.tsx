import { useEffect, useState } from 'react'
import { ExternalLink, FileText, X, ZoomIn, ZoomOut } from 'lucide-react'
import type { EvidenceRef } from '../evidence'
import { Chip, IconButton } from '../ui'

/** Right-hand drawer showing the real PDF page; the backend draws the highlight into the image. */
export function EvidenceDrawer({ evidence, renderUrl, onClose }: { evidence: EvidenceRef | null; renderUrl: string; onClose: () => void }) {
  const [zoom, setZoom] = useState(1)
  const [state, setState] = useState<'loading' | 'ok' | 'error'>('loading')
  const open = evidence !== null
  useEffect(() => {
    if (!open) return
    const h = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', h)
    return () => window.removeEventListener('keydown', h)
  }, [open, onClose])
  useEffect(() => { setZoom(1) }, [evidence?.doc_id, evidence?.page])
  useEffect(() => { setState('loading') }, [renderUrl])
  if (!evidence) return null
  return (
    <div className="fixed inset-0 z-50 flex justify-end">
      <button type="button" aria-label="Close evidence drawer" onClick={onClose} className="absolute inset-0 cursor-default bg-black/55 backdrop-blur-[1px]" />
      <aside role="dialog" aria-modal="true" aria-label={`Evidence: ${evidence.doc_name}, page ${evidence.page}`} className="relative flex h-full w-full max-w-[560px] flex-col border-l border-white/[0.1] bg-[#10151D] shadow-2xl">
        <header className="flex min-h-14 items-center gap-3 border-b border-white/[0.07] px-4">
          <FileText aria-hidden="true" size={16} className="shrink-0 text-sky-300" />
          <div className="min-w-0 flex-1">
            <h2 className="truncate text-[13px] font-semibold text-zinc-100">{evidence.doc_name}</h2>
            <p className="truncate text-[10px] text-zinc-500">Evidence source · {evidence.sentence_id ?? 'sentence id unavailable'}{evidence.nli_label ? ` · NLI ${evidence.nli_label}` : ''}</p>
          </div>
          <Chip tone="zinc">p.{evidence.page}</Chip>
          <a href={renderUrl} target="_blank" rel="noreferrer" aria-label="Open full page in new tab" title="Open full page in new tab" className="inline-flex h-8 w-8 items-center justify-center rounded-lg text-zinc-400 hover:bg-white/[0.07] hover:text-zinc-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-500/40"><ExternalLink aria-hidden="true" size={15} /></a>
          <IconButton icon={X} label="Close evidence" onClick={onClose} />
        </header>
        <div className="border-b border-white/[0.06] px-4 py-3">
          <div className="mb-1.5 text-[10px] font-semibold uppercase tracking-[0.12em] text-zinc-500">Verbatim quote · resolved by backend</div>
          <p className="border-l-2 border-sky-400 pl-3 font-mono text-[13px] leading-5 text-zinc-300">“{evidence.quote}”</p>
        </div>
        <div className="flex items-center justify-between border-b border-white/[0.06] px-4 py-2">
          <div className="flex items-center gap-2 text-[10px] text-zinc-500"><span className={`h-1.5 w-1.5 rounded-full ${state === 'ok' ? 'bg-emerald-400' : state === 'error' ? 'bg-rose-400' : 'bg-amber-400'}`} />{state === 'ok' ? 'Source page · highlight drawn server-side' : state === 'error' ? 'Render failed' : 'Rendering page…'}</div>
          <div className="flex items-center gap-1">
            <IconButton icon={ZoomOut} label="Zoom out" disabled={zoom <= 0.6} onClick={() => setZoom(z => Math.max(0.6, +(z - 0.2).toFixed(1)))} />
            <span className="w-10 text-center font-mono text-[10px] tabular-nums text-zinc-500">{Math.round(zoom * 100)}%</span>
            <IconButton icon={ZoomIn} label="Zoom in" disabled={zoom >= 2.4} onClick={() => setZoom(z => Math.min(2.4, +(z + 0.2).toFixed(1)))} />
          </div>
        </div>
        <div className="relative min-h-0 flex-1 overflow-auto bg-[#0A0E14] p-3">
          {state === 'loading' ? <div className="absolute inset-0 flex items-center justify-center text-xs text-zinc-500">Rendering page…</div> : null}
          {state === 'error' ? <div role="alert" className="rounded-lg bg-rose-400/[0.07] p-3 text-xs text-rose-200">Could not render this page from the backend.</div> : null}
          <img src={renderUrl} alt={`${evidence.doc_name} page ${evidence.page} with highlighted evidence`} style={{ width: `${zoom * 100}%`, maxWidth: 'none' }}
            className={`block rounded-sm bg-white shadow-xl ${state === 'ok' ? '' : 'invisible h-0'}`} onLoad={() => setState('ok')} onError={() => setState('error')} />
        </div>
      </aside>
    </div>
  )
}
