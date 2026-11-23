import { ChevronDown, FolderOpen, LockKeyhole, ShieldCheck } from 'lucide-react'
import type { Mode, Workspace } from '../../types'
import { MODES } from './modes'

const WORKSPACES: { id: Workspace; label: string }[] = [
  { id: 'bank_official', label: 'Bank Official' },
  { id: 'byo_private', label: 'BYO Private' },
]

export function TopBar({ workspace, mode, ollama, models, onWorkspaceChange, onModeChange, onToggleLibrary }: {
  workspace: Workspace
  mode: Mode
  /** `health.ollama` from /api/health, or null when the backend is unreachable. */
  ollama: string | null
  models: string
  onWorkspaceChange: (workspace: Workspace) => void
  onModeChange: (mode: Mode) => void
  onToggleLibrary: () => void
}) {
  const up = ollama === 'connected'
  return (
    <header className="relative z-40 h-14 shrink-0 border-b border-white/[0.07] bg-[#0A0E14]/95 backdrop-blur-xl">
      <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(ellipse_at_20%_0%,rgba(56,189,248,0.07),transparent_46%)]" />
      <div className="relative flex h-full items-center gap-3 px-3 sm:px-5">
        <button type="button" onClick={onToggleLibrary} aria-label="Toggle document library" className="rounded-lg p-1.5 text-zinc-400 hover:bg-white/[0.07] hover:text-zinc-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-500/40 lg:hidden"><FolderOpen aria-hidden="true" size={18} /></button>
        <div className="flex min-w-0 shrink-0 items-center gap-2.5">
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-emerald-400/10 text-emerald-300"><ShieldCheck aria-hidden="true" size={18} strokeWidth={1.75} /></div>
          <div className="min-w-0">
            <h1 className="truncate text-[13px] font-semibold tracking-tight text-zinc-100">Zero-Guessing Document AI</h1>
            <div className="hidden font-mono text-[9px] tracking-[0.14em] text-zinc-600 sm:block">AIML-02 · AUDIT WORKSPACE</div>
          </div>
        </div>
        <div className="hidden h-6 w-px bg-white/[0.08] md:block" />
        <div role="tablist" aria-label="Workspace" className="hidden items-center rounded-lg bg-white/[0.04] p-0.5 md:flex">
          {WORKSPACES.map(w => (
            <button key={w.id} type="button" role="tab" aria-selected={workspace === w.id} onClick={() => onWorkspaceChange(w.id)}
              className={`rounded-md px-2.5 py-1.5 text-[11px] transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-500/40 ${workspace === w.id ? 'bg-[#161D27] text-zinc-100 shadow-sm' : 'text-zinc-500 hover:text-zinc-300'}`}>{w.label}</button>
          ))}
        </div>
        <label className="ml-auto flex items-center text-[11px] text-zinc-500">
          <span className="sr-only">Mode</span>
          <select aria-label="Mode" value={mode} onChange={e => onModeChange(e.target.value as Mode)} className="appearance-none rounded-md bg-white/[0.04] py-1.5 pl-2.5 pr-6 text-[11px] text-zinc-300 outline-none focus-visible:ring-2 focus-visible:ring-sky-500/40">
            {MODES.map(m => <option key={m.id} value={m.id} className="bg-[#161D27]">{m.label}</option>)}
          </select>
          <ChevronDown aria-hidden="true" size={12} className="pointer-events-none -ml-5 text-zinc-500" />
        </label>
        <div className="hidden items-center gap-1.5 rounded-full bg-emerald-400/10 px-2.5 py-1.5 text-[10px] font-medium text-emerald-300 xl:flex"><LockKeyhole aria-hidden="true" size={12} />100% Local · Offline · Zero Paid APIs</div>
        <div className="hidden items-center gap-1.5 text-[10px] text-zinc-400 sm:flex" role="status">
          <span className={`h-2 w-2 rounded-full ${up ? 'bg-emerald-400' : 'bg-rose-400'}`} />Ollama {ollama ?? 'unreachable'}
        </div>
        <div className="hidden max-w-[260px] truncate font-mono text-[9px] text-zinc-600 2xl:block" title={models}>{models}</div>
      </div>
    </header>
  )
}
