# Data Model

Canonical data shapes used across ingestion, retrieval, verification, and UI.  
Use Pydantic models in `backend/app/models/` for runtime validation.

## 1. Ingestion

```python
from pydantic import BaseModel, Field
from typing import Literal, Optional

class BBox(BaseModel):
    x0: float
    y0: float
    x1: float
    y1: float
    page_width: float
    page_height: float

class Sentence(BaseModel):
    sentence_id: str            # "{chunk_id}#s{i}"
    chunk_id: str
    text: str
    page: int
    bbox: Optional[BBox] = None
    char_start: Optional[int] = None
    char_end: Optional[int] = None

class Chunk(BaseModel):
    chunk_id: str                      # e.g. "loan_v2_p3_c2"
    doc_id: str                        # stable id, e.g. hash or slug
    doc_name: str                      # original filename
    page: int                          # 1-indexed
    section: Optional[str] = None      # heading if detected
    text: str                          # raw extracted text
    normalized_text: str               # whitespace-normalized for matching
    chunk_type: Literal["paragraph", "table", "heading", "list", "other"] = "paragraph"
    bbox: Optional[BBox] = None        # for PDF highlight bonus
    sentences: list[Sentence] = Field(default_factory=list)
    char_start: Optional[int] = None
    char_end: Optional[int] = None
    metadata: dict = Field(default_factory=dict)

class Document(BaseModel):
    doc_id: str
    doc_name: str
    file_path: str
    num_pages: int
    ingested_at: str                   # ISO timestamp
    checksum: Optional[str] = None
```

**Notes:**
- `normalize_text(text)` collapses whitespace; use `casefold()` for matching.
- Chunk target: ~450 chars, ~80 overlap, avoid splitting mid-sentence when easy.
- `sentences` are deterministic spans over stored chunk text. `sentence_id` is stable and unique.
- `bbox` is best-effort. If unavailable, keep `null`.

## 2. Retrieval

```python
class RetrievedChunk(BaseModel):
    chunk: Chunk
    score: float                       # combined relevance score
    semantic_score: Optional[float] = None
    bm25_score: Optional[float] = None
    retrieval_rank: int

class RetrievalResult(BaseModel):
    query: str
    chunks: list[RetrievedChunk]
    total_indexed_chunks: int
```

## 3. Claims and citations

```python
class Citation(BaseModel):
    sentence_id: str
    chunk_id: str
    doc_id: str
    doc_name: str
    page: int
    quote: str                         # verbatim, backend-resolved from stored sentence
    bbox: Optional[BBox] = None
    verification_status: Literal["verified", "unverified", "failed"] = "unverified"
    support_status: Literal["supported", "contradicted", "not_enough_info", "unchecked"] = "unchecked"
    verification_notes: Optional[str] = None

class DraftClaim(BaseModel):
    claim_id: str
    text: str                          # 1 claim = 1 atomic sentence
    claim_type: Literal["factual", "numeric", "date", "rule", "definition", "other"] = "factual"
    source_ids: list[str] = Field(default_factory=list)  # LLM cites sentence_ids only

class Claim(BaseModel):
    claim_id: str
    text: str                          # 1 claim = 1 atomic sentence
    claim_type: str = "factual"
    status: Literal["supported", "contradicted", "unsupported", "abstained", "blocked"]
    source_ids: list[str] = Field(default_factory=list)
    citations: list[Citation] = Field(default_factory=list)
    reason: Optional[str] = None
```

**Verification invariants:**
- A `supported` claim has >= 1 citation with `verification_status == "verified"` and `support_status == "supported"`.
- `quote` is backend-resolved from stored sentence text; never LLM-free-typed.
- `sentence_id` resolves to a stored `Sentence` in a stored `Chunk`.
- `page`/`doc_name`/`bbox` come from stored metadata.

## 4. Contradictions

```python
class ContradictionValue(BaseModel):
    doc_id: str
    doc_name: str
    page: int
    chunk_id: str
    sentence_id: Optional[str] = None
    quote: str
    bbox: Optional[BBox] = None
    normalized_value: Optional[str] = None

class Contradiction(BaseModel):
    contradiction_id: str
    subject: str
    conflict_type: Literal["number", "date", "rule", "eligibility", "definition", "other"] = "other"
    severity: Literal["high", "medium", "low"] = "medium"
    status: Literal["confirmed", "possible"] = "possible"
    explanation: str
    values: list[ContradictionValue] = Field(default_factory=list)
    affected_claim_ids: list[str] = Field(default_factory=list)
```

**Rule:** conflicts explained by an `AMENDS`/`SUPERSEDES`/`REPLACES` edge are routed to amendment chains, not contradiction alerts.

## 5. Amendment chain

```python
class AmendmentEdge(BaseModel):
    edge_id: str
    from_doc_id: str                  # older/original document
    from_doc_name: str
    to_doc_id: str                    # amending document
    to_doc_name: str
    relation: Literal["AMENDS", "SUPERSEDES", "REPLACES"] = "AMENDS"
    effective_date: Optional[str] = None   # ISO date if known
    change_subject: Optional[str] = None
    old_value: Optional[str] = None
    new_value: Optional[str] = None
    evidence_chunk_id: str
    evidence_sentence_id: Optional[str] = None
    evidence_page: int
    evidence_quote: str
    confidence: float = 1.0

class AmendmentChain(BaseModel):
    chain_id: str
    subject: str
    doc_ids_ordered: list[str] = Field(default_factory=list)   # oldest -> newest/applicable
    edges: list[AmendmentEdge] = Field(default_factory=list)
    active_doc_id: Optional[str] = None
    active_rule: Optional[str] = None
    status: Literal["resolved", "ambiguous", "unresolved"] = "resolved"
```

## 6. Ask response

```python
class AskResponse(BaseModel):
    request_id: str
    question: str
    status: Literal["answered", "partially_answered", "abstained", "contradicted"]
    answer: str
    claims: list[Claim] = Field(default_factory=list)
    blocked_claims: list[Claim] = Field(default_factory=list)
    contradictions: list[Contradiction] = Field(default_factory=list)
    amendment_chains: list[AmendmentChain] = Field(default_factory=list)
    faithfulness_pct: Optional[float] = None
    verified_sentences_count: int = 0
    total_shown_sentences: int = 0
    blocked_claims_count: int = 0
    missing_evidence: list[str] = Field(default_factory=list)
    debug: Optional[dict] = None
```

## 7. Report

```python
class Report(BaseModel):
    report_id: str
    created_at: str
    question: str
    response: AskResponse
    format: Literal["html", "json", "markdown"] = "html"
    file_path: Optional[str] = None
```

## ID conventions

| Entity | Format | Example |
|---|---|---|
| doc_id | slug/hash | `loan_policy_2025` |
| chunk_id | `{doc_id}_p{page}_c{n}` | `loan_v2_p3_c2` |
| sentence_id | `{chunk_id}#s{n}` | `loan_v2_p3_c2#s0` |
| claim_id | `clm_{uuid8}` | `clm_a1b2c3d4` |
| contradiction_id | `ctr_{uuid8}` | `ctr_e5f6g7h8` |
| amendment edge | `ame_{uuid8}` | `ame_i9j0k1l2` |