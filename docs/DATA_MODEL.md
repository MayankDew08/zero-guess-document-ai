# Data Model

Canonical data shapes used across ingestion, retrieval, verification, and UI.  
Use Pydantic models in `backend/app/models/`.

## 1. Ingestion

```python
class BBox(BaseModel):
    x0: float; y0: float; x1: float; y1: float
    page_width: float; page_height: float

class Sentence(BaseModel):
    sentence_id: str            # "{chunk_id}#s{i}"
    chunk_id: str
    text: str
    page: int
    bbox: BBox | None = None
    char_start: int | None = None
    char_end: int | None = None

class Chunk(BaseModel):
    chunk_id: str               # "{doc_id}_p{page}_c{n}"
    doc_id: str
    doc_name: str
    page: int                   # 1-indexed
    section: str | None = None
    text: str
    normalized_text: str
    chunk_type: Literal["paragraph","table","heading","list","other"] = "paragraph"
    bbox: BBox | None = None
    sentences: list[Sentence] = []
    metadata: dict = {}

class Document(BaseModel):
    doc_id: str
    doc_name: str
    file_path: str
    num_pages: int
    ingested_at: str            # ISO timestamp
    chunks_created: int = 0
    checksum: str | None = None
```

**Notes:**
- `normalize_text` collapses whitespace; matching uses `casefold()`.
- Chunks target ~450 chars, ~80 overlap, avoid mid-sentence splits when easy.
- `sentences` are deterministic spans over stored chunk text. `sentence_id` is stable and unique.

## 2. Retrieval

```python
class RetrievedChunk(BaseModel):
    chunk: Chunk
    score: float                # hybrid RRF/combined score
    semantic_score: float | None = None
    bm25_score: float | None = None
    rerank_score: float | None = None
    retrieval_rank: int

class RetrievalResult(BaseModel):
    query: str
    chunks: list[RetrievedChunk]
    total_indexed_chunks: int
    crag_passed: bool = True
    max_rerank_score: float | None = None
```

## 3. Claims and citations

```python
class Citation(BaseModel):
    sentence_id: str
    chunk_id: str
    doc_id: str
    doc_name: str
    page: int
    quote: str                  # verbatim, backend-resolved
    bbox: BBox | None = None
    verification_status: Literal["verified","unverified","failed"] = "unverified"
    support_status: Literal["supported","contradicted","not_enough_info","unchecked"] = "unchecked"
    nli_label: str | None = None
    nli_scores: dict[str, float] | None = None
    verification_notes: str | None = None

class DraftClaim(BaseModel):
    claim_id: str
    text: str                   # 1 claim = 1 atomic sentence
    claim_type: Literal["factual","numeric","date","rule","definition","other"] = "factual"
    source_ids: list[str] = []  # LLM cites sentence_ids only

class Claim(BaseModel):
    claim_id: str
    text: str
    claim_type: str = "factual"
    status: Literal["supported","contradicted","unsupported","abstained","blocked"]
    source_ids: list[str] = []
    citations: list[Citation] = []
    reason: str | None = None
```

**Invariants:**
- A `supported` claim has >= 1 citation with `verification_status == "verified"` and `support_status == "supported"`.
- `quote` is backend-resolved from stored sentence text; never LLM-free-typed.
- `blocked_claims_count` counts draft claims blocked by verification gates.

## 4. Contradictions

```python
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
    conflict_type: Literal["number","date","rule","eligibility","definition","other"] = "other"
    severity: Literal["high","medium","low"] = "medium"
    status: Literal["confirmed","possible"] = "possible"
    explanation: str
    values: list[ContradictionValue] = []
    affected_claim_ids: list[str] = []
```

## 5. Amendment chain

```python
class AmendmentEdge(BaseModel):
    edge_id: str
    from_doc_id: str
    from_doc_name: str
    to_doc_id: str
    to_doc_name: str
    relation: Literal["AMENDS","SUPERSEDES","REPLACES"] = "AMENDS"
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
    doc_ids_ordered: list[str] = []
    edges: list[AmendmentEdge] = []
    active_doc_id: str | None = None
    active_doc_name: str | None = None
    active_rule: str | None = None
    status: Literal["resolved","ambiguous","unresolved"] = "resolved"
```

## 6. Ask response

```python
class AskResponse(BaseModel):
    request_id: str
    question: str
    status: Literal["answered","partially_answered","abstained","contradicted"]
    answer: str
    claims: list[Claim] = []
    blocked_claims: list[Claim] = []
    contradictions: list[Contradiction] = []
    amendment_chains: list[AmendmentChain] = []
    faithfulness_pct: float | None = None
    verified_sentences_count: int = 0
    total_shown_sentences: int = 0
    blocked_claims_count: int = 0
    missing_evidence: list[str] = []
    debug: dict | None = None
```

## ID conventions

| Entity | Format | Example |
|---|---|---|
| doc_id | slug/hash | `loan_policy_2025` |
| chunk_id | `{doc_id}_p{page}_c{n}` | `loan_v2_p3_c2` |
| sentence_id | `{chunk_id}#s{n}` | `loan_v2_p3_c2#s0` |
| claim_id | `clm_{uuid8}` | `clm_a1b2c3d4` |
| contradiction_id | `ctr_{uuid8}` | `ctr_e5f6g7h8` |
| edge_id | `ame_{uuid8}` | `ame_i9j0k1l2` |
| request_id | `req_{uuid12}` | `req_abc123def456` |
