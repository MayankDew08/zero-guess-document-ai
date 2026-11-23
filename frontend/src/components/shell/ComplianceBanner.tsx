import { Link2, Lock, ShieldAlert } from 'lucide-react'
import type { Mode, WorkspaceStats } from '../../types'
import { Chip } from '../ui'

/** Mode-specific strip under the top bar. Admin = live compliance audit from /api/workspaces/summary. */
export function ComplianceBanner({ mode, stats, docCount }: { mode: Mode; stats: WorkspaceStats | null; docCount: number }) {
  if (mode === 'byo') {
    return <div data-testid="banner-byo" className="flex shrink-0 items-center gap-2 border-b border-white/[0.06] border-l-2 border-l-violet-400 bg-[#0D1219] px-4 py-2 text-[11px] text-violet-200"><Lock aria-hidden="true" size={12} />Private local sandbox — your PDFs stay isolated from the bank policies.</div>
  }
  if (mode === 'customer') {
    return <div data-testid="banner-customer" className="flex shrink-0 items-center gap-2 border-b border-white/[0.06] border-l-2 border-l-emerald-400 bg-[#0D1219] px-4 py-2 text-[11px] text-emerald-200"><Lock aria-hidden="true" size={12} />Bank official policy server · read-only · {stats?.doc_count ?? docCount} verified policies</div>
  }
  const bad = (stats?.unresolved_contradictions_count ?? 0) > 0
  return (
    <div data-testid="banner-admin" className={`shrink-0 border-b border-white/[0.06] border-l-2 bg-[#0D1219] px-4 py-1.5 text-[10px] ${bad ? 'border-l-rose-400' : 'border-l-emerald-400'}`}>
      <div className="flex min-h-6 flex-wrap items-center gap-x-3 gap-y-1">
        <span className="font-semibold uppercase tracking-[0.12em] text-zinc-300">Compliance audit · Bank official corpus</span>
        {stats ? (
          <>
            <Chip tone={bad ? 'rose' : 'emerald'} className="px-2 py-1"><ShieldAlert aria-hidden="true" size={11} />{stats.unresolved_contradictions_count} unresolved contradiction{stats.unresolved_contradictions_count === 1 ? '' : 's'}</Chip>
            <Chip tone="sky" className="px-2 py-1"><Link2 aria-hidden="true" size={11} />{stats.amendment_chains_count} amendment chain{stats.amendment_chains_count === 1 ? '' : 's'}</Chip>
            <span className="tabular-nums text-zinc-500">{stats.doc_count} official docs · {stats.chunk_count} chunks</span>
          </>
        ) : <span className="text-zinc-500">loading live audit…</span>}
      </div>
      {stats && stats.contradiction_subjects.length > 0 ? <div className="mt-0.5 text-rose-200/80">Conflicting subjects: {stats.contradiction_subjects.join(', ')}</div> : null}
    </div>
  )
}
