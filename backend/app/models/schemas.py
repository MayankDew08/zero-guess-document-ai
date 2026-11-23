from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class BBox(BaseModel):
    x0: float
    y0: float
    x1: float
    y1: float
    page_width: float
    page_height: float


class Sentence(BaseModel):
    sentence_id: str
    chunk_id: str
    text: str
    page: int
    bbox: BBox | None = None
    char_start: int | None = None
    char_end: int | None = None


class Chunk(BaseModel):
    chunk_id: str
    doc_id: str
    doc_name: str
    page: int
    section: str | None = None
    text: str
    normalized_text: str = ""
    chunk_type: Literal["paragraph", "table", "heading", "list", "other"] = "paragraph"
    bbox: BBox | None = None
    sentences: list[Sentence] = Field(default_factory=list)
    metadata: dict = Field(default_factory=dict)


class Document(BaseModel):
    doc_id: str
    doc_name: str
    file_path: str
    num_pages: int
    ingested_at: str
    chunks_created: int = 0
    checksum: str | None = None


class RetrievedChunk(BaseModel):
    chunk: Chunk
    score: float = 0.0
    semantic_score: float | None = None
    bm25_score: float | None = None
    rerank_score: float | None = None
    retrieval_rank: int = 0
    via: str | None = None  # e.g. 'section_expansion:<chunk_id>' for multi-page clause continuations


class RetrievalResult(BaseModel):
    query: str
    chunks: list[RetrievedChunk] = Field(default_factory=list)
    total_indexed_chunks: int = 0
    crag_passed: bool = True
    max_rerank_score: float | None = None
    hybrid_candidates: int = 0
    reranked_kept: int = 0


class Citation(BaseModel):
    sentence_id: str
    chunk_id: str
    doc_id: str
    doc_name: str
    page: int
    quote: str
    bbox: BBox | None = None
    verification_status: Literal["verified", "unverified", "failed"] = "unverified"
    support_status: Literal["supported", "contradicted", "not_enough_info", "unchecked"] = "unchecked"
    nli_label: str | None = None
    nli_scores: dict[str, float] | None = None
    verification_notes: str | None = None


class DraftClaim(BaseModel):
    claim_id: str
    text: str
    claim_type: Literal["factual", "numeric", "date", "rule", "definition", "other"] = "factual"
    source_ids: list[str] = Field(default_factory=list)


class DraftAnswer(BaseModel):
    claims: list[DraftClaim] = Field(default_factory=list)
    missing_evidence: list[str] = Field(default_factory=list)


class Claim(BaseModel):

    claim_id: str
    text: str
    claim_type: str = "factual"
    status: Literal["supported", "contradicted", "unsupported", "abstained", "blocked"]
    source_ids: list[str] = Field(default_factory=list)
    citations: list[Citation] = Field(default_factory=list)
    reason: str | None = None
    numeric_verification: dict[str, Any] | None = None
    text_en: str | None = None  # verified English original when `text` is a verified Hindi rendering
    language: str = "en"



Claim.model_rebuild()


class ContradictionValue(BaseModel):
    doc_id: str
    doc_name: str
    page: int
    chunk_id: str
    sentence_id: str | None = None
    quote: str
    bbox: BBox | None = None
    normalized_value: str | None = None


class Contradiction(BaseModel):
    contradiction_id: str
    subject: str
    conflict_type: Literal["number", "date", "rule", "eligibility", "definition", "other"] = "other"
    severity: Literal["high", "medium", "low"] = "medium"
    status: Literal["confirmed", "possible"] = "possible"
    explanation: str
    values: list[ContradictionValue] = Field(default_factory=list)
    affected_claim_ids: list[str] = Field(default_factory=list)
    nli_contradiction_score: float | None = None


class AmendmentEdge(BaseModel):
    edge_id: str
    from_doc_id: str
    from_doc_name: str
    to_doc_id: str
    to_doc_name: str
    relation: Literal["AMENDS", "SUPERSEDES", "REPLACES"] = "AMENDS"
    effective_date: str | None = None
    change_subject: str | None = None
    old_value: str | None = None
    new_value: str | None = None
    evidence_chunk_id: str
    evidence_sentence_id: str | None = None
    evidence_page: int
    evidence_quote: str
    confidence: float = 1.0


class AmendmentChain(BaseModel):
    chain_id: str
    subject: str
    doc_ids_ordered: list[str] = Field(default_factory=list)
    doc_names_ordered: list[str] = Field(default_factory=list)
    edges: list[AmendmentEdge] = Field(default_factory=list)
    active_doc_id: str | None = None
    active_doc_name: str | None = None
    active_rule: str | None = None
    status: Literal["resolved", "ambiguous", "unresolved"] = "resolved"


class Calculation(BaseModel):
    """Deterministic working for a fee/penalty/interest/EMI question (never LLM arithmetic)."""
    kind: Literal["late_payment_fee", "interest", "emi"]
    formula: str
    inputs: dict[str, Any] = Field(default_factory=dict)
    steps: list[str] = Field(default_factory=list)
    result: str
    result_value: float
    citation: Citation | None = None
    warnings: list[str] = Field(default_factory=list)


class Gate1Trace(BaseModel):
    hybrid_candidates: int = 0
    reranked_kept: int = 0
    max_rerank_score: float | None = None
    threshold: float = 0.0
    passed: bool = False


class Gate2Trace(BaseModel):
    drafted_claims: int = 0
    resolved_citations: int = 0
    rejected_invalid_ids: int = 0


class Gate3Trace(BaseModel):
    nli_passed: int = 0
    nli_failed: int = 0
    numeric_passed: int = 0
    numeric_failed: int = 0


class Gate4Trace(BaseModel):
    amendment_chains_found: int = 0
    superseded_docs_filtered: int = 0
    unresolved_contradictions: int = 0
    abstained: bool = False


class PipelineTrace(BaseModel):
    """Lightweight per-request summary of the four deterministic gates."""
    gate1_retrieval: Gate1Trace = Field(default_factory=Gate1Trace)
    gate2_citation_resolution: Gate2Trace = Field(default_factory=Gate2Trace)
    gate3_nli_and_numeric: Gate3Trace = Field(default_factory=Gate3Trace)
    gate4_lineage_and_conflicts: Gate4Trace = Field(default_factory=Gate4Trace)


class AskRequest(BaseModel):
    question: str
    doc_ids: list[str] | None = None
    top_k: int | None = None
    debug: bool = False


class AskResponse(BaseModel):
    request_id: str
    question: str
    status: Literal["answered", "partially_answered", "abstained", "contradicted"]
    answer: str
    claims: list[Claim] = Field(default_factory=list)
    blocked_claims: list[Claim] = Field(default_factory=list)
    contradictions: list[Contradiction] = Field(default_factory=list)
    amendment_chains: list[AmendmentChain] = Field(default_factory=list)
    faithfulness_pct: float | None = None
    verified_sentences_count: int = 0
    total_shown_sentences: int = 0
    blocked_claims_count: int = 0
    drafted_claims_count: int = 0
    draft_support_pct: float | None = None
    missing_evidence: list[str] = Field(default_factory=list)
    calculation: Calculation | None = None
    pipeline_trace: PipelineTrace | None = None
    created_at: str | None = None
    language: str = "en"
    confidence: float | None = None
    confidence_breakdown: dict[str, float] | None = None
    debug: dict | None = None


class IngestResponse(BaseModel):
    documents: list[Document] = Field(default_factory=list)
    errors: list[dict] = Field(default_factory=list)


class ReportRequest(BaseModel):
    request_id: str | None = None
    response: AskResponse
    format: Literal["html", "json", "markdown"] = "html"


class ReportResponse(BaseModel):
    report_id: str
    format: str
    file_path: str
    download_url: str
