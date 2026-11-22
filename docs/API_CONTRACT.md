# API Contract

Base URL: `http://localhost:8000`

All responses are JSON unless noted. Errors use FastAPI's `{"detail": ...}` shape.

## 1. Health

### `GET /api/health`

Returns service status and model availability.

**Response 200**
```json
{
  "status": "ok",
  "ollama": "connected",
  "model": "qwen2.5:7b-instruct",
  "embedding_model": "sentence-transformers/all-MiniLM-L6-v2",
  "indexed_docs": 3,
  "indexed_chunks": 142
}
```

## 2. Ingestion

### `POST /api/ingest`

Upload one or more PDFs, parse/chunk/index them.

**Request:** `multipart/form-data`
- `files`: one or more PDF files

**Response 200**
```json
{
  "documents": [
    {
      "doc_id": "loan_v2",
      "doc_name": "Loan_Agreement_v2.pdf",
      "num_pages": 12,
      "chunks_created": 48,
      "indexed_at": "2026-11-22T20:05:00Z"
    }
  ],
  "errors": []
}
```

**Response 400/422** — invalid file type or parse failure.

### `GET /api/documents`

List indexed documents.

**Response 200**
```json
{
  "documents": [
    {
      "doc_id": "loan_v2",
      "doc_name": "Loan_Agreement_v2.pdf",
      "num_pages": 12,
      "chunks_created": 48,
      "indexed_at": "2026-11-22T20:05:00Z"
    }
  ]
}
```

## 3. Ask / Q&A

### `POST /api/ask`

Ask a question across indexed documents. Runs retrieval, structured claim drafting, deterministic source resolution, verification, contradiction/amendment checks, and faithfulness scoring.

**Request**
```json
{
  "question": "What is the late payment fee?",
  "doc_ids": ["loan_v1", "loan_v2"],
  "top_k": 8,
  "debug": false
}
```

- `doc_ids` optional; omit to search all indexed docs.
- `top_k` optional, default 8.
- `debug` optional; when true, include debug artifact in response.

**Response 200 (answered)**
```json
{
  "request_id": "req_abc123",
  "question": "What is the late payment fee?",
  "status": "answered",
  "answer": "The late payment fee is 2% per month after the due date.",
  "claims": [
    {
      "claim_id": "clm_001",
      "text": "The late payment fee is 2% per month after the due date.",
      "claim_type": "numeric",
      "status": "supported",
      "source_ids": ["loan_v2_p3_c2#s0"],
      "citations": [
        {
          "sentence_id": "loan_v2_p3_c2#s0",
          "chunk_id": "loan_v2_p3_c2",
          "doc_id": "loan_v2",
          "doc_name": "Loan_Agreement_v2.pdf",
          "page": 3,
          "quote": "A late payment fee of 2% per month applies after the due date.",
          "bbox": {
            "x0": 72.1,
            "y0": 144.3,
            "x1": 540.2,
            "y1": 168.9,
            "page_width": 612,
            "page_height": 792
          },
          "verification_status": "verified",
          "support_status": "supported",
          "verification_notes": "quote_matched;numeric_matched"
        }
      ],
      "reason": null
    }
  ],
  "blocked_claims": [],
  "contradictions": [],
  "amendment_chains": [],
  "faithfulness_pct": 100.0,
  "verified_sentences_count": 1,
  "total_shown_sentences": 1,
  "blocked_claims_count": 0,
  "missing_evidence": [],
  "debug": null
}
```

**Response 200 (abstained)**
```json
{
  "request_id": "req_abc124",
  "question": "What is the early closure penalty?",
  "status": "abstained",
  "answer": "I don't have proof in the provided documents to answer this question.",
  "claims": [],
  "blocked_claims": [],
  "contradictions": [],
  "amendment_chains": [],
  "faithfulness_pct": null,
  "verified_sentences_count": 0,
  "total_shown_sentences": 0,
  "blocked_claims_count": 0,
  "missing_evidence": [
    "No clause mentioning early closure penalty was found in indexed documents."
  ],
  "debug": null
}
```

**Response 200 (contradicted / partially answered with contradictions)**
```json
{
  "request_id": "req_abc125",
  "question": "What is the late payment fee?",
  "status": "contradicted",
  "answer": "The documents contain conflicting late payment fee values.",
  "claims": [],
  "blocked_claims": [],
  "contradictions": [
    {
      "contradiction_id": "ctr_001",
      "subject": "late payment fee",
      "conflict_type": "number",
      "severity": "high",
      "status": "confirmed",
      "explanation": "Different documents state different late payment fee percentages.",
      "values": [
        {
          "doc_id": "contract_a",
          "doc_name": "Contract_A.pdf",
          "page": 3,
          "chunk_id": "contract_a_p3_c1",
          "sentence_id": "contract_a_p3_c1#s0",
          "quote": "A late payment fee of 2% per month applies after the due date.",
          "bbox": null,
          "normalized_value": "2% per month"
        },
        {
          "doc_id": "contract_b",
          "doc_name": "Contract_B.pdf",
          "page": 2,
          "chunk_id": "contract_b_p2_c1",
          "sentence_id": "contract_b_p2_c1#s0",
          "quote": "A late payment fee of 5% per month applies after the due date.",
          "bbox": null,
          "normalized_value": "5% per month"
        }
      ],
      "affected_claim_ids": []
    }
  ],
  "amendment_chains": [],
  "faithfulness_pct": null,
  "verified_sentences_count": 0,
  "total_shown_sentences": 0,
  "blocked_claims_count": 0,
  "missing_evidence": [],
  "debug": null
}
```

## 4. Report generation

### `POST /api/report`

Generate a report for a completed `/api/ask` response.

**Request**
```json
{
  "request_id": "req_abc123",
  "response": { "...": "AskResponse object" },
  "format": "html"
}
```

**Response 200**
```json
{
  "report_id": "rep_001",
  "format": "html",
  "file_path": "data/reports/req_abc123.html",
  "download_url": "/api/report/rep_001/download"
}
```

### `GET /api/report/{report_id}/download`

Returns the generated report file (`text/html`, `application/json`, or `text/markdown` depending on format).

## 5. Debug / optional endpoints

### `POST /api/retrieve`

Dev-only endpoint to inspect retrieval before generation.

**Request**
```json
{ "question": "late payment fee", "top_k": 8 }
```

**Response 200**
```json
{
  "query": "late payment fee",
  "chunks": [
    {
      "chunk_id": "loan_v2_p3_c2",
      "doc_name": "Loan_Agreement_v2.pdf",
      "page": 3,
      "score": 0.82,
      "semantic_score": 0.79,
      "bm25_score": 0.85,
      "text": "A late payment fee of 2% per month applies after the due date."
    }
  ]
}
```

## Error behavior

| Condition | Status | Behavior |
|---|---:|---|
| No documents indexed | 400 | Ask user to ingest PDFs |
| Ollama unavailable | 503 | "Local model unavailable. Start Ollama and pull required model." |
| Invalid PDF | 400/422 | Report per-file parse error |
| LLM invalid JSON after retries | 200 | Return `abstained` with debug reason; never fabricate citations |
| Quote verification failure | 200 | Block claim/citation; include in `blocked_claims_count` |

## Contract rules

- Every displayed supported claim must have >= 1 verified citation with `quote`, `doc_name`, `page`, and `sentence_id`.
- `quote` is backend-resolved from stored chunk/sentence text. The LLM never free-types quotes.
- `faithfulness_pct` is computed over shown answer sentences/claims; `blocked_claims_count` reports draft claims blocked by verification.
- Conflicts explained by amendment edges go to `amendment_chains`, not `contradictions`.
- Frontend must render abstention and contradiction states distinctly.