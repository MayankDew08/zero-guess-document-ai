# AGENTS.md — Zero-Guessing Document AI

> Instructions for coding agents working in this repository. Read this file completely before making changes.

## Project goal

Build **Option B: Zero-Guessing & Contradiction-Checking Document AI** for Hackasol 5.0 (Track 2, AIML-02).  
The system answers questions across multiple PDFs using only verifiable evidence, flags contradictions, resolves amendment chains, and refuses to guess. **No paid AI APIs.** Everything runs on open-source models locally.

## Non-negotiable constraints

1. **No paid/external AI APIs.** No OpenAI, Anthropic, Gemini, Cohere, Voyage, etc. Use local open-source models only (Ollama / sentence-transformers / HuggingFace local).
2. **Every claim must be cited.** Each answer claim links to `doc_name`, `page`, and a backend-resolved **verbatim quote** from that page.
3. **Never invent evidence.** If a quote cannot be verified in the source, do not show it. If evidence is missing or contradictory, abstain explicitly.
4. **Faithfulness is measured, not claimed.** Compute `% sentences backed by >=1 verified source quote`. Report `faithfulness_pct` and `blocked_claims_count`.
5. **Local-first demo.** The app must run on a laptop with no internet dependency after models are downloaded.
6. **16 GB RAM discipline.** Load HuggingFace models (`BAAI/bge-reranker-v2-m3`, `MoritzLaurer/mDeBERTa-v3-base-mnli-xnli`) lazily as singletons in `fp16` where supported (CPU fallback cleanly). Never duplicate models in memory.

## Finalized model stack

| Role | Model | Notes |
|---|---|---|
| Generator LLM | `qwen2.5:7b-instruct` via Ollama | Fallback: `qwen2.5:3b-instruct` |
| Embeddings (EN+HI) | `BAAI/bge-m3` | `sentence-transformers` or Ollama backend |
| Reranker (EN+HI) | `BAAI/bge-reranker-v2-m3` | Top-12 hybrid -> top-5; CRAG abstention gate |
| NLI / contradiction (EN+HI) | `MoritzLaurer/mDeBERTa-v3-base-mnli-xnli` | True 3-class `entailment`/`neutral`/`contradiction`. **Never** use reranker as entailment proxy |

## Repo layout

```
.
├── AGENTS.md
├── README.md
├── OVERNIGHT_REPORT.md
├── docs/                    # Product, architecture, roadmap, eval, demo
├── backend/                 # FastAPI + Python pipeline
│   ├── app/
│   │   ├── main.py          # FastAPI app entry
│   │   ├── api/             # Route handlers
│   │   ├── core/            # Config, logging
│   │   ├── ingestion/       # PDF parsing, chunking, sentence spans
│   │   ├── retrieval/       # Embeddings, BM25, hybrid, reranker
│   │   ├── qa/              # LLM client, prompt, claim drafting
│   │   ├── verification/    # Citation resolve, NLI, numeric/date, abstention
│   │   ├── contradictions/  # Amendment-aware conflict detection
│   │   ├── amendments/      # Regex extraction, networkx DAG, resolver
│   │   ├── scoring/         # Faithfulness + blocked counts
│   │   ├── calculator/      # Optional deterministic calculator
│   │   └── models/          # Pydantic schemas
│   ├── tests/
│   ├── requirements.txt
│   ├── pyproject.toml
│   └── .env.example
├── frontend/                # Vite + React + TypeScript + Tailwind
│   └── src/
├── data/
│   ├── samples/             # Generated demo PDFs
│   ├── index/               # Generated index / sqlite / vectors
│   └── reports/             # Generated reports
└── scripts/                 # Sample generation, smoke tests
```

## Commands

Run from repo root unless noted.

### Backend
```bash
cd backend
python -m venv .venv && source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --reload --port 8000
```

### Frontend
```bash
cd frontend
npm install
npm run dev   # http://localhost:5173
```

### Tests
```bash
cd backend
pytest -q
```

### Lint / build
```bash
cd backend && ruff check .
cd frontend && npm run lint && npm run build
```

## Architecture rules

- **Backend is the source of truth.** Frontend never calls an LLM directly.
- **Verification is deterministic where possible.** Quote resolution, number/date comparison, faithfulness scoring must be code, not LLM vibes.
- **LLM outputs structured JSON.** Use Pydantic schemas and validate/repair. Never trust free-form citations.
- **LLM cites sentence_ids, never free-typed quotes.** The LLM cites `sentence_id` values (`chunk_id#sN`). The backend deterministically resolves `quote`, `doc_name`, `page`, and `bbox` from stored chunks.
- **Citations reference stored chunks/sentences.** A citation must resolve to stored data with known `doc_name`, `page`, `text`, and optional `bbox`.
- **Contradiction detection is amendment-aware.** Check amendment graph first. Conflicts explained by `AMENDS`/`SUPERSEDES`/`REPLACES` edges route to Amendment Chains, not Contradiction Alerts.
- **Abstention beats hallucination.** If verification fails, block the claim or return explicit "I don't have proof..." with missing evidence.
- **Provider interfaces for testability.** Embeddings, reranker, NLI, and Ollama LLM must have clean interfaces so tests use lightweight fakes/fixtures without multi-GB model downloads.

## Deterministic verification gates (exact order)

1. **Gate 1 (CRAG Pre-Generation):** If top reranker score `< RERANK_ABSTAIN_THRESHOLD`, abstain immediately without calling the LLM.
2. **Gate 2 (Citation Resolution):** Resolve `source_ids` to stored verbatim sentences. Invalid/missing IDs block the claim.
3. **Gate 3 (NLI + Numeric/Date Check):** Run `mDeBERTa-v3-base-mnli-xnli(premise=quote, hypothesis=claim)` AND deterministic regex verification that all numbers, percentages, currencies, durations, and dates in `claim` match `quote`. Block failing claims.
4. **Gate 4 (Abstention):** If 0 claims survive, return explicit `"I don't have proof..."` with `missing_evidence`.

## Data & evidence format

Every retrieved/stored chunk carries at minimum:

```json
{
  "chunk_id": "docA_p3_c2",
  "doc_id": "docA",
  "doc_name": "Loan_Agreement_v2.pdf",
  "page": 3,
  "section": "Late Payment",
  "text": "A late payment fee of 2% per month applies after the due date.",
  "bbox": [72.1, 144.3, 540.2, 168.9],
  "chunk_type": "paragraph",
  "sentences": [
    {
      "sentence_id": "docA_p3_c2#s0",
      "text": "A late payment fee of 2% per month applies after the due date.",
      "bbox": [72.1, 144.3, 540.2, 168.9]
    }
  ]
}
```

Every claim/citation shown to user carries:

```json
{
  "claim": "The late payment fee is 2% per month.",
  "status": "supported",
  "source_ids": ["docA_p3_c2#s0"],
  "citations": [
    {
      "sentence_id": "docA_p3_c2#s0",
      "chunk_id": "docA_p3_c2",
      "doc_name": "Loan_Agreement_v2.pdf",
      "page": 3,
      "quote": "A late payment fee of 2% per month applies after the due date.",
      "bbox": [72.1, 144.3, 540.2, 168.9]
    }
  ]
}
```

**Claim rule:** 1 claim = 1 atomic sentence. The LLM drafts claims with `source_ids` only; the backend resolves citations deterministically.

## Verification checklist before marking a feature done

- [ ] Quote appears verbatim (normalized whitespace) in the cited chunk/page.
- [ ] Citation page/doc metadata matches the stored chunk.
- [ ] Claim is entailed by quote, or explicitly marked unsupported/contradicted.
- [ ] Numbers/dates in claim match numbers/dates in cited evidence.
- [ ] 1 claim = 1 atomic sentence so claim-level and sentence-level faithfulness are identical.
- [ ] Return both `faithfulness_pct` and `blocked_claims_count`.
- [ ] UI shows abstention clearly; no blank/confident-sounding guess.

## When blocked

- If a model is too slow/heavy: switch to smaller quantized/fallback model; keep interface same.
- If PDF table extraction is messy: preserve raw text and mark table chunks; do not crash.
- If contradiction/amendment detection is ambiguous: show "possible conflict" with both quotes and low confidence, but never hide it.
- If you are unsure: add a failing test or TODO with explicit acceptance criteria, not a silent assumption.
