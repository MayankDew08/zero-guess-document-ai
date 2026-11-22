# OVERNIGHT_REPORT.md

## 1. What changed

### Docs / config synchronized to finalized architecture
- Updated `AGENTS.md`, `README.md`, `docs/TECH_STACK.md`, `docs/VERIFICATION_PIPELINE.md`, `docs/DATA_MODEL.md`, `docs/API_CONTRACT.md` to the finalized stack and gates.
- Updated `backend/.env.example`, `backend/requirements.txt`, added `backend/pyproject.toml`.
- Key finalized decisions reflected: `BAAI/bge-m3`, `BAAI/bge-reranker-v2-m3`, `MoritzLaurer/mDeBERTa-v3-base-mnli-xnli`, CRAG gate, LLM cites `source_ids` only, deterministic backend quote resolution, NLI+numeric/date gate, amendment-aware contradiction routing, `faithfulness_pct` + `blocked_claims_count`.

### Backend implemented (FastAPI + verification pipeline)
- `app/core`: config, logging, text normalization, persistent in-memory store.
- `app/ingestion`: PyMuPDF parser, deterministic chunking with sentence spans (`chunk_id#sN`), ingestion service, amendment edge extraction on ingest, index persistence.
- `app/retrieval`: embedding provider interface + sentence-transformers `bge-m3`, BM25, hybrid RRF retrieval, cross-encoder reranker `bge-reranker-v2-m3`, CRAG abstention gate. Lazy singletons; fake/fallback providers for testability and resilience.
- `app/qa`: Ollama LLM client with JSON parsing/repair, strict prompt (claims cite `source_ids` only), ask orchestrator.
- `app/verification`: citation/source resolution, mDeBERTa NLI verifier, deterministic numeric/date matcher, gate pipeline.
- `app/amendments`: regex amendment extraction, networkx DAG/chain builder.
- `app/contradictions`: amendment-aware contradiction detection (amendment-explained conflicts routed away from contradiction alerts).
- `app/scoring`: faithfulness over shown claims + blocked claim count.
- `app/main.py`: FastAPI app, CORS, health/docs/ingest/ingest-samples/ask/retrieve/report endpoints.

### Frontend implemented (Vite + React + TS + Tailwind)
- Upload PDFs, **Load Demo Sample PDFs** button, ask panel, answer status badge.
- Displays claims with backend-resolved citations (doc/page/verbatim quote/sentence_id), NLI label/score.
- Displays contradictions and amendment chains.
- Displays abstention/missing evidence, `faithfulness_pct`, blocked claim count.
- Report download/open via `/api/report`.

### Sample corpus and scripts
- `scripts/generate_samples.py` generates 4 demo PDFs in `data/samples/`:
  - `Acme_Loan_Policy_v1.pdf` (5% interest, 1% late fee, 12 months)
  - `Acme_Loan_Policy_v2.pdf` (6% interest, 2% late fee, 24 months; amends/supersedes v1)
  - `Acme_Loan_Policy_v3.pdf` (7% interest, 2% late fee, eligibility, fee table; supersedes v2)
  - `Acme_Operations_Notice.pdf` (5% late fee conflict; early closure info)

## 2. Exact commands run

```bash
# Baseline inspection
ls -la /home/dark/2026-11-22-track-2-aiml-computer-vision-619bec4f
find ... -maxdepth 3
git log/status

# Backend syntax check
cd backend && python -m py_compile app/core/config.py app/core/store.py app/models/schemas.py app/ingestion/parser.py app/ingestion/chunker.py app/ingestion/service.py app/retrieval/embeddings.py app/retrieval/bm25_index.py app/retrieval/reranker.py app/retrieval/service.py app/qa/llm.py app/qa/prompt.py app/qa/service.py app/verification/nli.py app/verification/numeric.py app/verification/pipeline.py app/amendments/graph.py app/contradictions/detector.py app/scoring/faithfulness.py app/main.py

# Backend tests
cd backend && python -m pytest -q
# Result: 7 passed

# Sample generation
python -m pip install reportlab -q
python scripts/generate_samples.py
# Result: Generated sample PDFs in .../data/samples

# Frontend
cd frontend && npm install
cd frontend && npm run build
# Result: vite build success

# Backend deps / smoke
cd backend && python -m pip install -q -r requirements.txt
cd backend && PYTHONPATH=. python -m uvicorn app.main:app --port 8001
curl http://localhost:8001/api/health
curl -X POST http://localhost:8001/api/ingest/samples
curl -X POST http://localhost:8001/api/ask -H 'Content-Type: application/json' -d '{"question":"What is the late payment fee according to the latest active rule?","debug":false}'
```

## 3. Verification results

- **Backend py_compile**: pass.
- **Backend pytest**: `7 passed` (`backend/tests/test_pipeline.py`).
  - Covers citation resolution blocking invalid source IDs, numeric mismatch blocking, NLI+numeric gate behavior, CRAG abstention below threshold, amendment-explained conflict not flagged as contradiction, faithfulness/blocked-claim reporting.
- **Frontend build**: `tsc -b && vite build` passed.
- **Live smoke (local env)**:
  - `/api/health` returned ok with finalized model names.
  - `/api/ingest/samples` ingested 4 generated PDFs (10 chunks total).
  - `/api/ask` returned a structured response with `status`, `claims`, `citations`, `contradictions`, `amendment_chains`, `faithfulness_pct`, `blocked_claims_count`. Real mDeBERTa NLI scores were present in the smoke response, indicating HF NLI model loaded in this environment.

## 4. Current model stack (exact)

| Role | Model |
|---|---|
| Generator LLM | `qwen2.5:7b-instruct` (Ollama), fallback `qwen2.5:3b-instruct` |
| Embeddings | `BAAI/bge-m3` (`sentence-transformers` by default; Ollama backend configurable) |
| Reranker | `BAAI/bge-reranker-v2-m3` (CrossEncoder, lazy singleton, CRAG gate) |
| NLI / contradiction | `MoritzLaurer/mDeBERTa-v3-base-mnli-xnli` (HF pipeline, lazy singleton, fp16 on CUDA when available) |

## 5. Known gaps / morning polish

- **Real end-to-end with Ollama model pulled**: smoke test hit `/api/ask` in an environment where Ollama was connected; full answer quality depends on `qwen2.5:7b-instruct` being pulled and responsive. If Ollama/model unavailable, the API now fails gracefully with abstention/missing-evidence.
- **Heavy model downloads**: first real run may download HF models (`bge-m3`, reranker, NLI). Ensure disk/RAM available; 16GB RAM target respected by lazy singleton + fp16 where supported.
- **PDF bbox granularity**: sentence bboxes currently inherit block bbox (PyMuPDF block extraction). Good for demo highlight; can be refined to word/span-level boxes.
- **Amendment extraction heuristics**: regex/heuristic-based; works for generated demo corpus and clear "amends/supersedes/replaces" language. Ambiguous cases should be surfaced carefully.
- **Contradiction detection**: combines NLI + numeric/date checks + retrieval heuristics; amendment graph consulted first. May need tuning thresholds on real corpus.
- **Frontend polish**: functional and build-passing; can add richer PDF preview overlay, clearer loading states, and doc selection filters.
- **Report format**: HTML/JSON/Markdown supported by backend; UI downloads HTML report.
- **Security/hardening**: prototype CORS/auth not hardened; intended for local demo.

## 6. How to demo

1. **Start Ollama** and pull model:
   ```bash
   ollama pull qwen2.5:7b-instruct
   ```
2. **Backend**:
   ```bash
   cd backend
   python -m venv .venv && source .venv/bin/activate
   pip install -r requirements.txt
   cp .env.example .env
   uvicorn app.main:app --reload --port 8000
   ```
3. **Frontend**:
   ```bash
   cd frontend
   npm install
   npm run dev
   ```
4. Open `http://localhost:5173`.
5. Click **Load Demo Sample PDFs** (calls `POST /api/ingest/samples`).
6. Ask: "What is the late payment fee according to the latest active rule?"
7. Show: verified claims with citations (doc/page/quote), faithfulness %, blocked claims count, contradiction alert (operations notice vs policy), amendment chain (v1→v2→v3), and abstention on an out-of-corpus question.
8. Click **Download Report** for audit artifact.
