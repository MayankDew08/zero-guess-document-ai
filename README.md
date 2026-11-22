# Zero-Guessing Document AI

Hackasol 5.0 — Track 2: AIML, **Option B (AIML-02)**.

A verifiable Document AI prototype that answers complex questions across multiple PDFs using **only exact, verifiable evidence**. It cites verbatim quotes, flags contradictions, resolves amendment chains, and refuses to guess when proof is missing. The full pipeline runs on **open-source models with no paid AI APIs**.

## What it does

| Capability | What the user sees |
|---|---|
| Multi-document evidence retrieval | Hybrid search across PDFs (bge-m3 + BM25 + reranker), including tables and multi-page sections. |
| Exact citations | Every claim links to document name, page number, and backend-resolved verbatim quote. |
| Contradiction detection | Amendment-aware conflicts shown side by side with both quotes. |
| Amendment chains | "Which rule applies today?" resolved with A→B→C chain and active rule. |
| Zero-guessing abstention | CRAG gate + NLI/numeric verification block unsupported claims; explicit missing-evidence response. |
| Faithfulness score | `Faithfulness: X% (A/B verified)` + `N unsupported draft claims blocked`. |

## Finalized model stack (local, no paid APIs)

| Role | Model | Notes |
|---|---|---|
| Generator LLM | `qwen2.5:7b-instruct` (Ollama) | Fallback `qwen2.5:3b-instruct` |
| Embeddings (EN+HI) | `BAAI/bge-m3` | sentence-transformers or Ollama backend |
| Reranker (EN+HI) | `BAAI/bge-reranker-v2-m3` | Lazy singleton, fp16/CPU fallback, top-12 -> top-5 |
| NLI / contradiction (EN+HI) | `MoritzLaurer/mDeBERTa-v3-base-mnli-xnli` | Lazy singleton, fp16/CPU fallback, true 3-class NLI |

## Quick start

### Prerequisites

- Python 3.11+
- Node 20+
- [Ollama](https://ollama.com/) installed
- 16 GB RAM minimum; GPU recommended for smoother demo

### 1. Pull local models

```bash
ollama pull qwen2.5:7b-instruct
ollama pull bge-m3   # if using Ollama embedding backend
```

> HuggingFace models (`BAAI/bge-m3` when using sentence-transformers, `BAAI/bge-reranker-v2-m3`, `MoritzLaurer/mDeBERTa-v3-base-mnli-xnli`) auto-download on first run. They are loaded lazily as singletons in fp16 where supported.

### 2. Backend

```bash
cd backend
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --reload --port 8000
```

Backend: http://localhost:8000  
API docs: http://localhost:8000/docs

### 3. Frontend

```bash
cd frontend
npm install
npm run dev
```

Frontend: http://localhost:5173

### 4. Generate demo sample PDFs

```bash
python scripts/generate_samples.py
```

Then use the UI "Load Demo Sample PDFs" button, or call `POST /api/ingest/samples`.

## Verification pipeline

```text
PDFs -> Parse/Chunk (sentence IDs + bbox)
     -> Index (bge-m3 embeddings + BM25) + Amendment Graph (regex + networkx DAG)
     -> Hybrid Retrieve (RRF top-12)
     -> Rerank (bge-reranker-v2-m3 top-5)
     -> Gate 1: CRAG abstain if max_rerank_score < threshold
     -> Draft atomic claims citing source_ids only (qwen2.5:7b-instruct JSON)
     -> Gate 2: Resolve source_ids -> verbatim quotes/metadata (deterministic)
     -> Gate 3: mDeBERTa NLI entailment + numeric/date regex check
     -> Amendment-aware contradiction detection
     -> Gate 4: Abstain if no claims survive
     -> Faithfulness score + blocked_claims_count -> Render
```

## Tests

```bash
cd backend
pytest -q
ruff check .
```

Frontend build:

```bash
cd frontend
npm run lint
npm run build
```

Live smoke test (requires Ollama running and models pulled):

```bash
python scripts/smoke_test_live.py
```

## Project docs

| Doc | Purpose |
|---|---|
| [AGENTS.md](AGENTS.md) | Rules for coding agents |
| [docs/ROADMAP.md](docs/ROADMAP.md) | Timeline and cut lines |
| [docs/PRD.md](docs/PRD.md) | Requirements and acceptance criteria |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | System design and data flow |
| [docs/VERIFICATION_PIPELINE.md](docs/VERIFICATION_PIPELINE.md) | Zero-guessing verification design |
| [docs/DATA_MODEL.md](docs/DATA_MODEL.md) | Schemas |
| [docs/API_CONTRACT.md](docs/API_CONTRACT.md) | Backend API contract |
| [docs/DATASET_AND_EVAL.md](docs/DATASET_AND_EVAL.md) | Sample corpus and evaluation |
| [docs/DEMO_SCRIPT.md](docs/DEMO_SCRIPT.md) | Demo script |
| [docs/TECH_STACK.md](docs/TECH_STACK.md) | Stack choices and setup |

## No-paid-API compliance

- No OpenAI/Anthropic/Gemini/Cohere/Voyage/paid SDKs.
- No external AI endpoints in request path.
- LLM, embeddings, reranker, NLI all run locally.
- After model download, demo can run without internet.
