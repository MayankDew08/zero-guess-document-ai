# API Contract

Base URL: `http://localhost:8000`

All responses are JSON unless noted. Errors use FastAPI's `{"detail": ...}` shape.

## 1. Health

### `GET /api/health`
Returns service status and model/index availability.

```json
{
  "status": "ok",
  "ollama": "connected",
  "model": "qwen2.5:7b-instruct",
  "embedding_model": "BAAI/bge-m3",
  "reranker_model": "BAAI/bge-reranker-v2-m3",
  "nli_model": "MoritzLaurer/mDeBERTa-v3-base-mnli-xnli",
  "indexed_docs": 3,
  "indexed_chunks": 142
}
```

## 2. Ingestion

### `POST /api/ingest`
Multipart upload. Field: `files` (one or more PDFs).

Response 200:
```json
{
  "documents": [{"doc_id":"loan_v2","doc_name":"Loan_Agreement_v2.pdf","num_pages":12,"chunks_created":48,"indexed_at":"..."}],
  "errors": []
}
```

### `POST /api/ingest/samples`
Loads PDFs from `data/samples/`. Used by the UI "Load Demo Sample PDFs" button.

Response 200: same shape as `/api/ingest`.

### `GET /api/documents`
Lists indexed documents.

## 3. Ask / Q&A

### `POST /api/ask`

Request:
```json
{
  "question": "What is the late payment fee?",
  "doc_ids": ["loan_v1","loan_v2"],
  "top_k": 8,
  "debug": false
}
```

Response 200 (answered/abstained/contradicted/partially_answered):
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
          "bbox": {"x0":72.1,"y0":144.3,"x1":540.2,"y1":168.9,"page_width":612,"page_height":792},
          "verification_status": "verified",
          "support_status": "supported",
          "nli_label": "entailment",
          "nli_scores": {"entailment":0.98,"neutral":0.01,"contradiction":0.01},
          "verification_notes": "quote_resolved;nli_entailment;numeric_match"
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

## 4. Report

### `POST /api/report`
Request: `{"request_id":"...","response":{...AskResponse...},"format":"html"}`  
Response: `{"report_id":"rep_001","format":"html","file_path":"...","download_url":"/api/report/rep_001/download"}`

### `GET /api/report/{report_id}/download`
Returns generated report file.

## 5. Debug / dev

### `POST /api/retrieve`
Dev endpoint to inspect retrieval/reranking without generation.

## Contract rules

- Every displayed supported claim has >= 1 verified citation with `quote`, `doc_name`, `page`, and `sentence_id`.
- `quote` is backend-resolved from stored chunk/sentence text. LLM never free-types quotes.
- `faithfulness_pct` is computed over shown answer sentences/claims; `blocked_claims_count` reports draft claims blocked by verification.
- Conflicts explained by amendment edges go to `amendment_chains`, not `contradictions`.
- Frontend must render abstention and contradiction states distinctly.
