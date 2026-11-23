export interface Citation {
  sentence_id: string;
  chunk_id: string;
  doc_id: string;
  doc_name: string;
  page: number;
  quote: string;
  bbox?: any;
  verification_status: string;
  support_status: string;
  nli_label?: string | null;
  nli_scores?: Record<string, number> | null;
  verification_notes?: string | null;
}

export interface PipelineTrace {
  gate1_retrieval: { hybrid_candidates: number; reranked_kept: number; max_rerank_score: number | null; threshold: number; passed: boolean };
  gate2_citation_resolution: { drafted_claims: number; resolved_citations: number; rejected_invalid_ids: number };
  gate3_nli_and_numeric: { nli_passed: number; nli_failed: number; numeric_passed: number; numeric_failed: number };
  gate4_lineage_and_conflicts: { amendment_chains_found: number; superseded_docs_filtered: number; unresolved_contradictions: number; abstained: boolean };
}

export interface Claim {
  claim_id: string;
  text: string;
  claim_type: string;
  status: 'supported' | 'contradicted' | 'unsupported' | 'abstained' | 'blocked';
  source_ids: string[];
  citations: Citation[];
  reason?: string | null;
  text_en?: string | null;
  language?: string;
}

export interface Contradiction {
  contradiction_id: string;
  subject: string;
  conflict_type: string;
  severity: string;
  status: string;
  explanation: string;
  values: any[];
}

export interface Calculation {
  kind: string;
  formula: string;
  inputs: Record<string, any>;
  steps: string[];
  result: string;
  result_value: number;
  citation?: Citation | null;
  warnings: string[];
}

export interface AmendmentChain {
  chain_id: string;
  subject: string;
  doc_ids_ordered: string[];
  doc_names_ordered?: string[];
  edges: any[];
  active_doc_id?: string | null;
  active_doc_name?: string | null;
  active_rule?: string | null;
  status: string;
}

export interface AskResponse {
  request_id: string;
  question: string;
  status: 'answered' | 'partially_answered' | 'abstained' | 'contradicted';
  answer: string;
  claims: Claim[];
  blocked_claims: Claim[];
  contradictions: Contradiction[];
  amendment_chains: AmendmentChain[];
  faithfulness_pct: number | null;
  verified_sentences_count: number;
  total_shown_sentences: number;
  blocked_claims_count: number;
  drafted_claims_count?: number;
  draft_support_pct?: number | null;
  missing_evidence: string[];
  calculation?: Calculation | null;
  pipeline_trace?: PipelineTrace | null;
  created_at?: string | null;
  language?: string;
  confidence?: number | null;
  confidence_breakdown?: Record<string, number> | null;
  explanation?: any;
  debug?: any;
  workspace?: Workspace;
  rewritten_question?: string | null;
  clarification_needed?: ClarificationNeeded | null;
}

export type Workspace = 'bank_official' | 'byo_private';
export type Mode = 'admin' | 'customer' | 'byo';

export interface MissingField { key: string; label: string; placeholder: string }
export interface ClarificationNeeded {
  kind: 'calculation_inputs';
  message: string;
  missing_fields: MissingField[];
  base_question: string;
  pending_calculation: Record<string, any>;
}

/** Sent as `history`; only used server-side to resolve follow-ups. Never evidence. */
export interface ChatTurn {
  role: 'user' | 'assistant';
  question: string;
  answer_summary: string;
  pending_calculation: Record<string, any> | null;
}

export interface WorkspaceStats {
  doc_count: number; chunk_count: number; amendment_chains_count: number; unresolved_contradictions_count: number;
  contradiction_subjects: string[]; doc_names: string[];
}
export type WorkspacesSummary = Record<Workspace, WorkspaceStats>;

export interface CorpusSummary {
  documents: number; pages: number; chunks: number; table_chunks: number; sentences: number;
  amendment_edges: number; superseded_docs: number; indexed: boolean;
}

/** One pipeline stage snapshot from /api/ask/stream. Later events for the same `stage` overwrite earlier ones. */
export interface StageEvent {
  stage: string;
  status: 'start' | 'done' | 'skipped';
  detail: Record<string, any>;
  ms: number | null;
}
