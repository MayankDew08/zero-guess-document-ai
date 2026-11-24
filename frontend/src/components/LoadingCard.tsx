import { Check, LoaderCircle, Minus, Timer } from 'lucide-react'
import { Collapse } from './ui'
import { STAGE_DEFS, fmtMs, stageDetail, type ClientStage } from './stages'

/** Live checklist of the verification pipeline, driven only by real stage events from the backend. */
export function LoadingCard({ elapsedSeconds, stages }: { elapsedSeconds: number; stages: ClientStage[] }) {
  const byKey = new Map(stages.map(s => [s.stage, s]))
  const rerankPassed = byKey.get('rerank')?.detail?.passed as boolean | undefined
  const rows = STAGE_DEFS.filter(d => !d.optional || byKey.has(d.key))
  const loading = stages.find(s => s.status === 'start' && s.detail.loading_model)
  const doneCount = rows.filter(d => { const s = byKey.get(d.key); return s && s.status !== 'start' }).length
  return (
    <section role="status" aria-live="polite" className="rounded-xl bg-[#10151D] px-4 py-4 ring-1 ring-inset ring-white/[0.06]">
      <div className="flex items-center gap-2 text-sm font-medium text-zinc-100">
        <LoaderCircle aria-hidden="true" size={16} className="animate-spin text-sky-300" />
        Verifying locally
        <span className="ml-auto font-mono text-xs tabular-nums text-zinc-400">{doneCount}/{rows.length} steps · {elapsedSeconds}s</span>
      </div>
      <ol className="mt-3 space-y-1">
        {rows.map(d => {
          const s = byKey.get(d.key)
          const state = !s ? 'pending' : s.status === 'start' ? 'active' : s.status
          const detail = stageDetail(s, rerankPassed)
          const live = state === 'active' && s ? Math.max(0, Math.round((Date.now() - s.t) / 1000)) : null
          return (
            <li key={d.key} data-state={state} className={`flex items-start gap-3 rounded-lg px-2.5 py-2 ${state === 'active' ? 'bg-sky-400/[0.08] ring-1 ring-inset ring-sky-400/20' : ''}`}>
              <span aria-hidden="true" className="mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center">
                {state === 'done' ? <Check size={14} className="text-emerald-400" strokeWidth={2.5} />
                  : state === 'active' ? <LoaderCircle size={14} className="animate-spin text-sky-300" />
                  : state === 'skipped' ? <Minus size={14} className="text-zinc-500" />
                  : <span className="h-1.5 w-1.5 rounded-full bg-zinc-600" />}
              </span>
              <div className="min-w-0 flex-1">
                <div className={`text-[13px] leading-5 ${state === 'pending' ? 'text-zinc-500' : state === 'skipped' ? 'text-zinc-400' : 'text-zinc-100'}`}>
                  {d.label}{d.sub ? <span className="ml-2 text-[11px] text-zinc-500">{d.sub}</span> : null}
                </div>
                {detail ? <div className={`text-[11px] leading-4 ${s?.detail.loading_model ? 'text-amber-300' : 'text-zinc-400'}`}>{detail}</div> : null}
              </div>
              <span className="shrink-0 pt-0.5 font-mono text-[11px] tabular-nums text-zinc-400">
                {state === 'done' && s?.ms != null ? fmtMs(s.ms) : live !== null ? `${live}s` : ''}
              </span>
            </li>
          )
        })}
      </ol>
      <p className="mt-3 text-[11px] leading-5 text-zinc-500">
        {loading ? `Loading ${String(loading.detail.loading_model).split('/').pop()} — first use only, this can take 30s or more. ` : ''}
        Every claim is checked before display; no data leaves this machine.
      </p>
    </section>
  )
}


/** Completed per-stage timings, kept collapsed after the live LoadingCard is replaced by the answer. */
export function PipelineRunCard({ stages }: { stages: ClientStage[] }) {
  const byKey = new Map(stages.map(s => [s.stage, s]))
  const rerankPassed = byKey.get('rerank')?.detail?.passed as boolean | undefined
  const rows = STAGE_DEFS.filter(d => byKey.has(d.key))
  if (rows.length === 0) return null
  const totalMs = rows.reduce((sum, d) => sum + (byKey.get(d.key)?.ms ?? 0), 0)
  return (
    <Collapse title={<span className="text-xs font-medium text-zinc-300">Pipeline run · {rows.length} step{rows.length === 1 ? '' : 's'}</span>}
      className="rounded-lg bg-[#161D27] px-3.5 py-3" icon={Timer}
      trailing={<span className="mr-1 font-mono text-[10px] tabular-nums text-zinc-500">{totalMs > 0 ? fmtMs(totalMs) : '—'}</span>}>
      <ol className="space-y-0.5">
        {rows.map(d => {
          const s = byKey.get(d.key)!
          const detail = stageDetail(s, rerankPassed)
          return (
            <li key={d.key} className="flex items-start gap-2.5 rounded-lg px-2 py-1.5">
              <span aria-hidden="true" className="mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center">
                {s.status === 'skipped' ? <Minus size={13} className="text-zinc-500" />
                  : s.status === 'done' ? <Check size={13} className="text-emerald-400" strokeWidth={2.5} />
                  : <span className="h-1.5 w-1.5 rounded-full bg-zinc-600" />}
              </span>
              <div className="min-w-0 flex-1">
                <div className="text-[11px] leading-4 text-zinc-300">
                  {d.label}{d.sub ? <span className="ml-2 text-[10px] text-zinc-500">{d.sub}</span> : null}
                </div>
                {detail ? <div className="text-[10px] leading-4 text-zinc-500">{detail}</div> : null}
              </div>
              <span className="shrink-0 pt-0.5 font-mono text-[10px] tabular-nums text-zinc-500">
                {s.ms != null ? fmtMs(s.ms) : '—'}
              </span>
            </li>
          )
        })}
      </ol>
    </Collapse>
  )
}
