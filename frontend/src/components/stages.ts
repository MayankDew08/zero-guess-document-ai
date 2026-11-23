import type { StageEvent } from '../types'

/** A stage event plus the browser time (ms) its stage first appeared — used for the live per-stage timer. */
export type ClientStage = StageEvent & { t: number }

/** Merge by stage key: later events overwrite earlier ones (the pipeline never replays a stage). */
export function mergeStage(list: ClientStage[], e: StageEvent): ClientStage[] {
  const i = list.findIndex(s => s.stage === e.stage)
  if (i < 0) return [...list, { ...e, t: Date.now() }]
  const next = list.slice()
  next[i] = { ...e, t: list[i].t }
  return next
}

export interface StageDef { key: string; label: string; sub?: string; optional?: boolean }

/** Display order. Optional stages only appear when the backend actually runs them. */
export const STAGE_DEFS: StageDef[] = [
  { key: 'understand', label: 'Resolve follow-up question', optional: true },
  { key: 'retrieve', label: 'Embed & hybrid retrieval', sub: 'bge-m3 + BM25' },
  { key: 'rerank', label: 'Rerank + relevance gate', sub: 'bge-reranker-v2-m3 · CRAG' },
  { key: 'draft', label: 'Draft claims from evidence', sub: 'local LLM' },
  { key: 'resolve', label: 'Resolve citations', sub: 'Gate 2' },
  { key: 'verify', label: 'NLI + number/date check', sub: 'Gate 3 · mDeBERTa' },
  { key: 'repair', label: 'Re-check blocked claims', optional: true },
  { key: 'translate', label: 'Verified Hindi rendering', optional: true },
  { key: 'lineage', label: 'Amendment & contradiction analysis', sub: 'Gate 4' },
]

export const fmtMs = (ms: number) => (ms < 1000 ? `${ms}ms` : `${(ms / 1000).toFixed(1)}s`)

/** Human detail line built only from real values in `detail`. */
export function stageDetail(s: ClientStage | undefined, rerankPassed: boolean | undefined): string {
  if (!s) return ''
  const d = s.detail
  if (s.status === 'skipped') return rerankPassed === false ? 'skipped — no relevant evidence' : 'not needed'
  if (d.loading_model) return `loading ${String(d.loading_model).split('/').pop()} (first use)…`
  const n = (v: unknown) => (typeof v === 'number' ? v : undefined)
  switch (s.stage) {
    case 'retrieve': return [n(d.parts) && n(d.parts)! > 1 ? `${d.parts} sub-questions` : '', n(d.candidates) !== undefined ? `${d.candidates} candidates` : ''].filter(Boolean).join(' · ')
    case 'rerank': return s.status === 'done' && n(d.kept) !== undefined
      ? `kept ${d.kept} · top ${d.max_score == null ? 'n/a' : Number(d.max_score).toFixed(2)} vs ${d.threshold} · ${d.passed ? 'relevant' : 'below threshold — will abstain'}` : ''
    case 'draft': return n(d.claims) !== undefined ? `${d.claims} claim${d.claims === 1 ? '' : 's'} drafted` : ''
    case 'resolve': return n(d.resolved) !== undefined ? `${d.resolved} resolved · ${d.rejected} rejected` : n(d.claims) !== undefined ? `${d.claims} claim${d.claims === 1 ? '' : 's'}` : ''
    case 'verify': return n(d.nli_passed) !== undefined ? `NLI ${d.nli_passed} pass / ${d.nli_failed} fail · numeric ${d.numeric_failed} fail` : ''
    case 'repair': return n(d.claims) !== undefined ? `${d.claims} replacement claim${d.claims === 1 ? '' : 's'}` : ''
    case 'lineage': return n(d.chains) !== undefined ? `${d.chains} chain${d.chains === 1 ? '' : 's'} · ${d.conflicts} conflict${d.conflicts === 1 ? '' : 's'}` : ''
    default: return ''
  }
}
