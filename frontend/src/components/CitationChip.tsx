import { FileText } from 'lucide-react'
import type { Citation } from '../types'
import { Chip } from './ui'
import { toEvidenceRef, type EvidenceRef, type OpenEvidence } from './evidence'

/** Clickable doc/page chip; opens the highlighted PDF page in the evidence drawer. */
export function RefChip({ evidenceRef, onOpenEvidence, compact = false }: {
  evidenceRef: EvidenceRef; onOpenEvidence: OpenEvidence; compact?: boolean
}) {
  return (
    <Chip tone="sky" onClick={() => onOpenEvidence(evidenceRef)} title={`Open ${evidenceRef.doc_name}, page ${evidenceRef.page}`} ariaLabel={`Open ${evidenceRef.doc_name}, page ${evidenceRef.page}`} className={`${compact ? 'px-2 py-1' : 'px-2.5 py-1.5'} max-w-full`}>
      <FileText aria-hidden="true" size={12} strokeWidth={1.75} className="shrink-0" />
      <span className="min-w-0 truncate">{evidenceRef.doc_name}</span>
      <span className="shrink-0">· p.{evidenceRef.page}</span>
    </Chip>
  )
}

export function CitationChip({ citation, onOpenEvidence, compact = false }: { citation: Citation; onOpenEvidence: OpenEvidence; compact?: boolean }) {
  return <RefChip evidenceRef={toEvidenceRef(citation)} onOpenEvidence={onOpenEvidence} compact={compact} />
}

/** Verbatim quote block; clicking opens the same evidence. */
export function QuoteButton({ evidenceRef, onOpenEvidence, accent = 'border-sky-400', className = '' }: {
  evidenceRef: EvidenceRef; onOpenEvidence: OpenEvidence; accent?: string; className?: string
}) {
  return (
    <button type="button" onClick={() => onOpenEvidence(evidenceRef)} title="Open highlighted source page" aria-label={`Open quote on page ${evidenceRef.page}`}
      className={`block w-full border-l-2 ${accent} pl-3 text-left font-mono text-[13px] leading-5 text-zinc-300 hover:text-zinc-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-500/40 ${className}`}>
      “{evidenceRef.quote}”
    </button>
  )
}
