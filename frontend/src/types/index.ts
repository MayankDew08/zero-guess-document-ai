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
}

export interface Claim {
  claim_id: string;
  text: string;
  claim_type: string;
  status: 'supported' | 'contradicted' | 'unsupported' | 'abstained' | 'blocked';
  source_ids: string[];
  citations: Citation[];
  reason?: string | null;
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

export interface AmendmentChain {
  chain_id: string;
  subject: string;
  doc_ids_ordered: string[];
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
  missing_evidence: string[];
  debug?: any;
}
