import type { Citation } from '../types'

/** What the evidence drawer needs to render a highlighted PDF page. */
export type EvidenceRef = { doc_id: string; doc_name: string; page: number; sentence_id?: string | null; quote: string; nli_label?: string | null }
export type OpenEvidence = (ref: EvidenceRef) => void

export function toEvidenceRef(c: Citation): EvidenceRef {
  return { doc_id: c.doc_id, doc_name: c.doc_name, page: c.page, sentence_id: c.sentence_id, quote: c.quote, nli_label: c.nli_label ?? null }
}

/** Backend-resolved shapes that `AskResponse` types as `any[]`. */
export interface ContradictionValue {
  doc_id: string; doc_name: string; page: number; chunk_id: string; sentence_id?: string | null; quote: string; normalized_value?: string | null
}
export interface AmendmentEdge {
  edge_id: string; from_doc_id: string; from_doc_name: string; to_doc_id: string; to_doc_name: string
  relation: string; effective_date?: string | null; change_subject?: string | null; old_value?: string | null; new_value?: string | null
  evidence_chunk_id: string; evidence_sentence_id?: string | null; evidence_page: number; evidence_quote: string
}
