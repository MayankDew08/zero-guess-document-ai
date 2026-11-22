# AGENTS.md — Zero-Guessing Document AI

> Instructions for coding agents working in this repository. Read this file completely before making changes.

## Project goal

Build **Option B: Zero-Guessing & Contradiction-Checking Document AI** for Hackasol 5.0 (Track 2, AIML-02).  
The system answers questions across multiple PDFs using only verifiable evidence, flags contradictions, resolves amendment chains, and refuses to guess. **No paid AI APIs.** Everything runs on open-source models locally.

## Non-negotiable constraints

1. **No paid/external AI APIs.** No OpenAI, Anthropic, Gemini, Cohere, Voyage, etc. Use local open-source models only (Ollama / sentence-transformers / HuggingFace local).
2. **Every claim must be cited.** Each answer claim links to `document_name`, `page_number`, and a **verbatim quote** from that page.
3. **Never invent evidence.** If a quote cannot be verified in the source, do not show it. If evidence is missing or contradictory, abstain explicitly.
4. **Faithfulness is measured, not claimed.** Compute `% sentences backed by >=1 verified source quote`.
5. **Local-first demo.** The app must run on a laptop with no internet dependency after models are downloaded.

## Repo layout

```
.
├── AGENTS.md
├── README.md
├── docs/                    # Product, architecture, roadmap, eval, demo
├── backend/                 # FastAPI + Python pipeline
│   ├── app/
│   │   ├── main.py          # FastAPI app entry
│   │   ├── api/             # Route handlers
│   │   ├── ingestion/       # PDF parsing, chunking
│   │   ├── retrieval/       # Embeddings, vector/BM25 search
│   │   ├── qa/              # Answer generation, claim extraction
│   │   ├── verification/    # Citation check, NLI/support, abstention
│   │   ├── contradictions/  # Conflict detection
│   │   ├── amendments/      # Amendment graph + resolver
│   │   ├── scoring/         # Faithfulness score
│   │   └── models/          # Pydantic schemas
│   ├── tests/
│   ├── requirements.txt
│   └── pyproject.toml
├── frontend/                # Vite + React + TypeScript + Tailwind
│   └── src/
├── data/
│   ├── samples/             # Sample PDFs for demo/eval
│   ├── index/               # Generated vector index / sqlite
│   └── reports/             # Generated reports
└── scripts/                 # Dev/eval scripts
```

## Commands

Run from repo root unless noted.

### Backend
```bash
cd backend
python -m venv .venv && source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env   # set OLLAMA_MODEL, EMBEDDING_MODEL, DATA_DIR
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
pytest tests/test_verification.py -q   # focus on verification
```

### Lint/format (if configured)
```bash
cd backend && ruff check . && ruff format .
cd frontend && npm run lint
```

## Architecture rules

- **Backend is the source of truth.** Frontend never calls an LLM directly.
- **Verification is deterministic where possible.** Quote matching, number/date comparison, faithfulness scoring must be code, not LLM vibes.
- **LLM outputs structured JSON.** Use Pydantic schemas and validate/repair. Never trust free-form citations.
- **LLM cites sentence_ids, never free-typed quotes.** The LLM cites `sentence_id` values (`chunk_id#sN`). The backend deterministically resolves `quote`, `doc_name`, `page`, and `bbox` from stored chunks.
- **Citations reference stored chunks.** A citation must resolve to a stored chunk/sentence with known `doc_name`, `page`, `text`, and optional `bbox`.
- **Contradiction detection is amendment-aware.** Contradiction detection must consult the amendment graph first—conflicts explained by an `AMENDS`/`SUPERSEDES` edge are routed to Amendment Chains, not Contradiction Alerts.
- **Abstention beats hallucination.** If verification fails, the claim is blocked or the answer becomes "I don't have proof of X. Missing: ..."

## Coding conventions

- Python: type hints, small pure functions, Pydantic models for API/schema boundaries.
- Keep modules narrow: parsing != retrieval != verification != UI.
- Prefer simple, inspectable heuristics before fancy models. Hackathon judges can read code.
- Add tests for every verification rule and contradiction/amendment case.
- Do not add paid SDKs, telemetry, or cloud dependencies.
- Log intermediate artifacts (retrieved chunks, draft claims, verification results) to aid debugging and demo.

## Data & evidence format

Every retrieved/stored chunk should carry at minimum:

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

Chunks must include deterministic sentence spans. You may also reference sentences by the `chunk_id#sN` convention; either form is acceptable as long as sentence IDs are stable, unique, and resolved from stored chunk text.

Every claim/citation shown to user should carry:

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
- [ ] Return both `faithfulness_pct` (verified shown sentences / total shown sentences) and `blocked_claims_count` (draft claims blocked by verifier).
- [ ] UI shows abstention clearly; no blank/confident-sounding guess.

## When blocked

- If a model is too slow/heavy: switch to smaller quantized model; keep interface same.
- If PDF table extraction is messy: preserve raw text and mark table chunks; do not crash.
- If contradiction/amendment detection is ambiguous: show "possible conflict" with both quotes and low confidence, but never hide it.
- If you are unsure: add a failing test or TODO with explicit acceptance criteria, not a silent assumption.

## Read next

- `docs/ROADMAP.md` — hour-by-hour plan and cut lines.
- `docs/PRD.md` — must-have/bonus requirements mapped to acceptance tests.
- `docs/ARCHITECTURE.md` — components and data flow.
- `docs/VERIFICATION_PIPELINE.md` — the core zero-guessing logic.
- `docs/AGENT_TASKS.md` — copy-paste task prompts for coding agents.