# Architecture — Zero-Guessing Document AI

## System overview

```text
                        +---------------------------+
                        |      React Frontend       |
                        | Upload | Q&A | Evidence UI |
                        +-------------+-------------+
                                      | HTTP/JSON
                                      v
                        +---------------------------+
                        |        FastAPI API        |
                        | /ingest /ask /report ...  |
                        +-------------+-------------+
                                      |
          +---------------------------+---------------------------+
          |                           |                           |
          v                           v                           v
+-------------------+     +-----------------------+     +----------------------+
|  Ingestion        |     | Retrieval             |     | Verification         |
|  PyMuPDF parsing  |     | Embeddings + FAISS    |     | Quote match          |
|  chunking/tables  |     | BM25 keyword          |     | Support/NLI          |
+---------+---------+     | hybrid top-k          |     | Number/date checks   |
          |               +-----------+-----------+     +----------+-----------+
          v                           |                            |
+-------------------+                 |                            v
| Local Store       |<----------------+              +---------------------------+
| chunks.json/SQLite|                                | Reasoning Modules         |
| FAISS index       |                                | Contradiction detector    |
| amendment graph   |                                | Amendment resolver        |
+-------------------+                                | Faithfulness scorer       |
                                                     +-------------+-------------+
                                                                   |
                                                                   v
                                                     +---------------------------+
                                                     | Verified Response          |
                                                     | claims + citations         |
                                                     | abstentions/conflicts      |
                                                     | faithfulness score         |
                                                     +---------------------------+
```

## Component responsibilities

### 1. Frontend (`frontend/`)
- Upload/select PDFs.
- Ask questions and show chat/history.
- Render answer claims with citation chips/cards.
- Show contradiction side-by-side panel.
- Show amendment chain timeline.
- Show faithfulness score and abstention banner.
- Bonus: PDF.js page view with highlighted bbox.

### 2. API layer (`backend/app/api/`)
- `POST /api/ingest` — ingest PDFs from upload or sample dir.
- `POST /api/ask` — run full Q&A + verification pipeline.
- `GET /api/documents` — list indexed docs.
- `GET /api/documents/{doc_id}/pages/{page}` — page text/image/bboxes for highlight.
- `POST /api/report` — generate report for a question/session.

### 3. Ingestion (`backend/app/ingestion/`)
- Parse digital PDFs with PyMuPDF.
- Extract page text blocks, basic table text, bounding boxes.
- Chunk by semantic blocks with size/overlap controls.
- Normalize whitespace but preserve raw quote text for verbatim citation.
- Store chunk metadata.

### 4. Retrieval (`backend/app/retrieval/`)
- Embed chunks with sentence-transformers.
- Index vectors in FAISS.
- Optional BM25 over chunk text for exact terms/numbers/dates.
- Hybrid retrieval: merge semantic and keyword results, dedupe by `chunk_id`.
- Return top-k chunks with scores and metadata.

### 5. QA / claim drafting (`backend/app/qa/`)
- Build prompt with question + retrieved chunks.
- Ask local LLM (Ollama) for **structured JSON** output.
- LLM drafts claims with `source_ids` only (`chunk_id#sN`); no free-typed quotes.
- Backend deterministically resolves `source_ids` to verbatim `quote`, `doc_name`, `page`, and `bbox` from stored chunks.
- Constrain: "use only provided evidence; if missing, say so; cite sentence IDs only."

### 6. Verification (`backend/app/verification/`)
- **Source resolver:** `source_id` resolves to stored sentence/chunk; copy verbatim quote and metadata.
- **Quote verifier:** resolved quote must appear in cited chunk (normalized match).
- **Support verifier:** claim entailed by evidence (rule-based, optional NLI, or LLM verifier prompt).
- **Numeric/date verifier:** numbers/dates in claim must match evidence.
- **Abstention gate:** unsupported/contradicted claims removed or converted to explicit missing-evidence response; compute `faithfulness_pct` and `blocked_claims_count`.

### 7. Contradiction detector (`backend/app/contradictions/`)
- Group evidence by subject/field.
- Extract comparable values (numbers, dates, percentages, named conditions).
- Flag conflicts for same subject.
- Emit contradiction records with both quotes and locations.

### 8. Amendment resolver (`backend/app/amendments/`)
- Detect amendment relations in text/metadata.
- Build graph edges: `from_doc -> to_doc`, `effective_date`, `change_summary`, evidence quote.
- Resolve current applicable rule by effective date / latest superseding edge.
- Return chain for UI.

### 9. Scoring/report (`backend/app/scoring/`)
- Faithfulness = supported answer sentences / total answer sentences * 100.
- Generate report containing question, verified answer, abstentions, contradictions, amendment chain, citations, faithfulness.

## Data flow — ask question

```text
User question
  -> retrieve(question, top_k)
  -> draft_claims(question, chunks)            # LLM, structured JSON
  -> verify_claims(claims, chunks)             # deterministic + NLI/LLM
  -> detect_contradictions(question, chunks)   # rules + optional LLM
  -> resolve_amendments(question, chunks/docs) # graph/patterns
  -> score_faithfulness(verified_answer)
  -> abstain_or_render(response)
```

## Key design decisions

### Structured claims, not free-form chat
The LLM drafts claims in JSON. This makes verification possible. Free-form answers are converted to claim/sentence units before scoring.

### Deterministic checks first
Quote presence, page existence, number/date equality, and faithfulness math are code. LLMs are used where language understanding is needed, not where string equality suffices.

### Abstention is a first-class output
The API can return `status=abstained` or partially supported answers with blocked claims. The UI must render this as a clear state, not an error.

### Local-only by default
Ollama and sentence-transformers run locally. No external AI endpoint in request path.

## State and storage

| Data | Storage | Notes |
|---|---|---|
| Uploaded PDFs | `data/samples/` or upload dir | Keep original filename and doc_id |
| Parsed chunks | `data/index/chunks.json` or SQLite | Source of truth for citations |
| Vector index | `data/index/faiss.index` | Rebuildable from chunks |
| BM25 corpus | in-memory or serialized pickle/json | Rebuildable |
| Amendment graph | `data/index/amendments.json` | Derived from docs, editable for demo |
| Reports | `data/reports/*.html` | Generated artifacts |

## Error handling

| Failure | Behavior |
|---|---|
| PDF parse fails | Return ingestion error for that file; continue others |
| No chunks retrieved | Abstain with "No relevant evidence found" |
| LLM returns invalid JSON | Retry with repair prompt; if still bad, abstain safely |
| Quote verification fails | Block claim; do not display fabricated citation |
| Ollama unavailable | Return clear 503 with "local model unavailable" |
| Contradiction/amendment module uncertain | Show "possible" with evidence, or omit if no evidence |

## Observability for debugging/demo

Log per request:
- question
- retrieved chunk IDs and scores
- raw LLM draft (dev mode)
- verification decisions per claim
- contradictions/amendments found
- final faithfulness score

Expose dev endpoint or write `data/reports/debug_<id>.json` during hackathon. Disable noisy logs in final demo if needed.
