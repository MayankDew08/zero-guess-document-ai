import { useRef, useState, type DragEvent } from 'react'
import { Activity, FileText, FolderOpen, Trash2, Upload, X } from 'lucide-react'
import type { CorpusSummary, Mode } from '../../types'

export interface LibraryDoc { doc_id: string; doc_name: string; num_pages: number; chunks_created: number }

export function LibrarySidebar({ mode, docs, summary, pending, progress, busy, canManage, open, onClose, onPickFiles, onRemovePending, onUpload, onLoadSamples, onDeleteDoc, onClear }: {
  mode: Mode
  docs: LibraryDoc[]
  summary: CorpusSummary | null
  pending: File[]
  progress: { pct: number; phase: string } | null
  /** 'upload' | 'samples' | 'clear' | a doc_id being deleted | null */
  busy: string | null
  canManage: boolean
  open: boolean
  onClose: () => void
  onPickFiles: (files: FileList | File[]) => void
  onRemovePending: (index: number) => void
  onUpload: () => void
  onLoadSamples: () => void
  onDeleteDoc: (docId: string) => void
  onClear: () => void
}) {
  const [dragging, setDragging] = useState(false)
  const input = useRef<HTMLInputElement>(null)
  const onDrop = (e: DragEvent<HTMLDivElement>) => { e.preventDefault(); setDragging(false); onPickFiles(e.dataTransfer.files) }
  const title = mode === 'byo' ? 'My private documents' : mode === 'customer' ? 'Official policies' : 'Official policy library'
  const emptyText = mode === 'byo' ? 'No private documents yet — drop a PDF above.' : mode === 'customer' ? 'The bank has not published any policies yet.' : 'No documents indexed yet.'
  const stats: [string, string | number][] = summary ? [
    ['Documents', summary.documents], ['Pages', summary.pages], ['Chunks', `${summary.chunks} (${summary.table_chunks} tbl)`],
    ['Citable sentences', summary.sentences], ['Amendment edges', summary.amendment_edges], ['Superseded', summary.superseded_docs],
  ] : []
  const working = busy !== null
  return (
    <>
      {open ? <button type="button" aria-label="Close library" onClick={onClose} className="absolute inset-0 z-20 bg-black/50 lg:hidden" /> : null}
      <aside className={`absolute inset-y-0 left-0 z-30 w-72 flex-col border-r border-white/[0.07] bg-[#0D1219] ${open ? 'flex' : 'hidden'} lg:static lg:z-auto lg:flex lg:shrink-0`}>
        <div className="min-h-0 flex-1 overflow-y-auto">
          {canManage ? (
            <div className="space-y-3 p-4">
              <div onDragEnter={e => { e.preventDefault(); setDragging(true) }} onDragOver={e => e.preventDefault()}
                onDragLeave={e => { if (!e.currentTarget.contains(e.relatedTarget as Node | null)) setDragging(false) }} onDrop={onDrop}
                className={`rounded-xl border border-dashed px-3 py-4 text-center transition-colors ${dragging ? 'border-sky-400 bg-sky-400/[0.08]' : 'border-white/[0.12] bg-white/[0.02]'}`}>
                <Upload aria-hidden="true" size={16} className="mx-auto text-zinc-500" />
                <p className="mt-2 text-xs font-medium text-zinc-300">Drag &amp; drop PDFs here</p>
                <p className="mt-1 text-[10px] text-zinc-600">{mode === 'byo' ? 'Stays in your isolated workspace' : 'Indexed into the official corpus'}</p>
                <input ref={input} type="file" multiple accept=".pdf,application/pdf" className="sr-only" aria-label="Upload PDF documents" onChange={e => { if (e.target.files) onPickFiles(e.target.files); e.target.value = '' }} />
                <button type="button" onClick={() => input.current?.click()} className="mt-2 rounded-md px-2 py-1 text-[10px] text-sky-300 hover:bg-sky-400/10 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-500/40">Browse PDFs</button>
              </div>
              {pending.length > 0 ? (
                <div className="space-y-1.5">
                  {pending.map((f, i) => (
                    <div key={`${f.name}-${i}`} className="flex items-center justify-between gap-2 rounded-lg bg-[#10151D] px-2.5 py-1.5 text-[11px] text-zinc-300">
                      <span className="truncate" title={f.name}>{f.name}</span>
                      <button type="button" aria-label={`Remove ${f.name}`} disabled={working} onClick={() => onRemovePending(i)} className="text-zinc-500 hover:text-rose-300 disabled:opacity-40"><X aria-hidden="true" size={12} /></button>
                    </div>
                  ))}
                  <button type="button" onClick={onUpload} disabled={working} className="inline-flex min-h-8 w-full items-center justify-center rounded-lg bg-sky-500 px-2 text-[11px] font-semibold text-sky-950 hover:bg-sky-400 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-300/50 disabled:opacity-50">
                    Upload &amp; index {pending.length} file{pending.length > 1 ? 's' : ''}
                  </button>
                </div>
              ) : null}
              {progress ? (
                <div role="progressbar" aria-valuenow={progress.pct} aria-valuemin={0} aria-valuemax={100}>
                  <div className="h-1.5 overflow-hidden rounded-full bg-white/[0.07]"><div className={`h-full rounded-full bg-sky-400 transition-[width] ${progress.phase === 'indexing' ? 'animate-pulse' : ''}`} style={{ width: `${progress.pct}%` }} /></div>
                  <div className="mt-1.5 text-[10px] text-zinc-400">{progress.phase === 'uploading' ? `Uploading… ${progress.pct}%` : 'Parsing, chunking & embedding (bge-m3)…'}</div>
                </div>
              ) : null}
              <div className="grid grid-cols-2 gap-2">
                {mode === 'admin' ? (
                  <button type="button" onClick={onLoadSamples} disabled={working} className="inline-flex min-h-8 items-center justify-center gap-1.5 rounded-lg bg-sky-500 px-2 text-[10px] font-semibold text-sky-950 transition hover:bg-sky-400 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-300/50 disabled:opacity-50"><FolderOpen aria-hidden="true" size={13} />{busy === 'samples' ? 'Indexing…' : 'Load Demo PDFs'}</button>
                ) : null}
                <button type="button" onClick={onClear} disabled={working || docs.length === 0} className={`inline-flex min-h-8 items-center justify-center gap-1.5 rounded-lg bg-white/[0.04] px-2 text-[10px] text-zinc-400 transition hover:bg-rose-400/10 hover:text-rose-300 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-500/40 disabled:opacity-40 ${mode === 'admin' ? '' : 'col-span-2'}`}><Trash2 aria-hidden="true" size={12} />{busy === 'clear' ? '…' : 'Clear All'}</button>
              </div>
            </div>
          ) : null}
          <div className="px-3 pb-4">
            <div className="mb-2 flex items-center justify-between px-1"><h2 className="text-[10px] font-semibold uppercase tracking-[0.12em] text-zinc-500">{title}</h2><span className="font-mono text-[10px] tabular-nums text-zinc-600">{docs.length}</span></div>
            <ul className="space-y-1">
              {docs.map(d => (
                <li key={d.doc_id} className="group flex items-center gap-2 rounded-lg px-2 py-2 transition hover:bg-white/[0.04]">
                  <FileText aria-hidden="true" size={14} className="shrink-0 text-zinc-500" />
                  <div className="min-w-0 flex-1"><p className="truncate text-[11px] text-zinc-300" title={d.doc_name}>{d.doc_name}</p><p className="mt-0.5 text-[10px] tabular-nums text-zinc-600">{d.num_pages} pg · {d.chunks_created} chunks</p></div>
                  {canManage ? <button type="button" aria-label={`Delete ${d.doc_name}`} title={`Delete ${d.doc_name}`} disabled={working} onClick={() => onDeleteDoc(d.doc_id)} className="rounded-md p-1 text-zinc-600 opacity-0 transition hover:bg-rose-400/10 hover:text-rose-300 focus-visible:opacity-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-500/40 disabled:opacity-30 group-hover:opacity-100">{busy === d.doc_id ? <span className="text-[10px]">…</span> : <X aria-hidden="true" size={13} />}</button> : null}
                </li>
              ))}
              {docs.length === 0 ? <li className="rounded-lg px-2 py-4 text-center text-[11px] text-zinc-600">{emptyText}</li> : null}
            </ul>
            {summary ? (
              <section className="mt-5">
                <div className="mb-2 flex items-center gap-2 px-1"><Activity aria-hidden="true" size={13} className="text-zinc-500" /><h2 className="text-[10px] font-semibold uppercase tracking-[0.12em] text-zinc-500">Corpus health</h2></div>
                <div className="grid grid-cols-2 gap-1.5">
                  {stats.map(([label, value]) => <div key={label} className="rounded-lg bg-[#10151D] px-2.5 py-2"><div className="font-mono text-[14px] tabular-nums text-zinc-200">{value}</div><div className="mt-0.5 text-[9px] leading-3 text-zinc-600">{label}</div></div>)}
                </div>
                <div className={`mt-3 flex items-center gap-2 px-1 text-[10px] ${summary.indexed ? 'text-emerald-300' : 'text-amber-300'}`}><span className={`h-1.5 w-1.5 rounded-full ${summary.indexed ? 'bg-emerald-400' : 'bg-amber-400'}`} />Vector index {summary.indexed ? 'ready' : 'building…'}</div>
              </section>
            ) : null}
          </div>
        </div>
      </aside>
    </>
  )
}
