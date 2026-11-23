import { useState } from 'react'
import { ChevronDown, Link2, Lock, ShieldAlert } from 'lucide-react'
import type { Mode, WorkspaceStats } from '../../types'
import { Chip } from '../ui'

/** Mode-specific strip under the top bar. Admin = live compliance audit from /api/workspaces/summary.
 *  Below `md` it is one compact line; the conflicting subjects open on tap. */
export function ComplianceBanner({ mode, stats, docCount }: { mode: Mode; stats: WorkspaceStats | null; docCount: number }) {
  const [open, setOpen] = useState(false)
  if (mode === 'byo') {
    return <div data-testid="banner-byo" className="flex shrink-0 items-center gap-2 border-b border-white/[0.06] border-l-2 border-l-violet-400 bg-[#0D1219] px-4 py-2 text-[11px] text-violet-200"><Lock aria-hidden="true" size={12} className="shrink-0" /><span className="truncate">Private local sandbox — <span className="hidden sm:inline">your PDFs stay isolated from the bank policies.</span><span className="sm:hidden">isolated from bank policies</span></span></div>
  }
  if (mode === 'customer') {
    return <div data-testid="banner-customer" className="flex shrink-0 items-center gap-2 border-b border-white/[0.06] border-l-2 border-l-emerald-400 bg-[#0D1219] px-4 py-2 text-[11px] text-emerald-200"><Lock aria-hidden="true" size={12} className="shrink-0" /><span className="truncate">Bank official policy server · read-only · {stats?.doc_count ?? docCount} verified policies</span></div>
  }
  const bad = (stats?.unresolved_contradictions_count ?? 0) > 0
  const subjects = stats && stats.contradiction_subjects.length > 0 ? stats.contradiction_subjects.join(', ') : ''
  return (
    <div data-testid="banner-admin" className={`shrink-0 border-b border-white/[0.06] border-l-2 bg-[#0D1219] px-4 py-1.5 text-[10px] ${bad ? 'border-l-rose-400' : 'border-l-emerald-400'}`}>
      <div className="flex min-h-6 items-center gap-x-3 gap-y-1 md:flex-wrap">
        <span className="hidden font-semibold uppercase tracking-[0.12em] text-zinc-300 md:inline">Compliance audit · Bank official corpus</span>
        {stats ? (
          <>
            <Chip tone={bad ? 'rose' : 'emerald'} className="shrink-0 px-2 py-1"><ShieldAlert aria-hidden="true" size={11} />{stats.unresolved_contradictions_count}<span className="hidden sm:inline">&nbsp;unresolved contradiction{stats.unresolved_contradictions_count === 1 ? '' : 's'}</span><span className="sm:hidden">&nbsp;conflict{stats.unresolved_contradictions_count === 1 ? '' : 's'}</span></Chip>
            <Chip tone="sky" className="shrink-0 px-2 py-1"><Link2 aria-hidden="true" size={11} />{stats.amendment_chains_count}<span className="hidden sm:inline">&nbsp;amendment chain{stats.amendment_chains_count === 1 ? '' : 's'}</span><span className="sm:hidden">&nbsp;chain{stats.amendment_chains_count === 1 ? '' : 's'}</span></Chip>
            <span className="hidden tabular-nums text-zinc-400 sm:inline">{stats.doc_count} official docs · {stats.chunk_count} chunks</span>
            {subjects ? <button type="button" aria-expanded={open} onClick={() => setOpen(o => !o)} className="ml-auto inline-flex items-center gap-1 text-zinc-400 md:hidden">subjects<ChevronDown aria-hidden="true" size={12} className={open ? 'rotate-180' : ''} /></button> : null}
          </>
        ) : <span className="text-zinc-400">loading live audit…</span>}
      </div>
      {subjects ? <div className={`mt-0.5 text-rose-200/80 ${open ? '' : 'hidden md:block'}`}>Conflicting subjects: {subjects}</div> : null}
    </div>
  )
}
