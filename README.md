# Zero-Guessing Document AI

Hackasol 5.0 — Track 2: AIML, **Option B (AIML-02)**.

A verifiable Document AI prototype that answers complex questions across multiple PDFs using **only exact, verifiable evidence**. It cites verbatim quotes, flags contradictions, resolves amendment chains, and refuses to guess when proof is missing. The full pipeline runs on **open-source models with no paid AI APIs**.

## What it does

| Capability | What the user sees |
|---|---|
| Multi-document evidence retrieval | Search across several PDFs, including tables and multi-page sections. |
| Exact citations | Every claim links to document name, page number, and verbatim quote. |
| Contradiction detection | Conflicting numbers/dates/rules/eligibility shown side by side. |
| Amendment chains | "Which rule applies today?" resolved with A→B→C change chain. |
| Zero-guessing abstention | Unsupported/contradicted claims blocked with missing-evidence explanation. |
| Faithfulness score | `% of answer sentences backed by >=1 matching source quote`. |

## Quick start

### Prerequisites

- Python 3.11+
- Node 20+
- [Ollama](https://ollama.com/) installed
- 16 GB RAM minimum; GPU recommended for smoother demo

### 1. Pull local models

```bash
ollama pull qwen2.5:7b-instruct
ollama pull bge-m3
```

> HuggingFace local models (`BAAI/bge-reranker-v2-m3` and `MoritzLaurer/mDeBERTa-v3-base-mnli-xnli`) auto-download on first run (and run in fp16/ONNX to fit 16 GB RAM).
> If RAM/GPU is tight, use `qwen2.5:3b-instruct` as the generator fallback and keep prompts short.

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

## Demo flow

1. Upload 2+ PDFs (or use `data/samples/`).
2. Ask a question that spans documents.
3. Inspect answer: each claim has citations with page + verbatim quote.
4. Ask a question that hits conflicting clauses — see side-by-side contradiction alert.
5. Ask "Which rule applies today?" across amended docs — see amendment chain.
6. Ask for something not in the docs — see explicit abstention and missing evidence.
7. Check faithfulness score badge.

See `docs/DEMO_SCRIPT.md` for the full judge demo.

## Verification pipeline (short)

```text
PDFs -> Parse/Chunk (with sentence IDs + bbox) -> Index (bge-m3 + BM25) + Amendment Graph
  -> Hybrid Retrieve -> Rerank (bge-reranker-v2-m3) -> CRAG Abstention Gate
  -> Draft atomic sentence claims citing sentence_ids
  -> Resolve exact quotes -> Verify (mDeBERTa NLI + number/date match)
  -> Resolve Amendment Chain -> Detect Unresolved Contradictions
  -> Compute Faithfulness + Blocked Count -> Render Answer
```

Full detail: `docs/VERIFICATION_PIPELINE.md`.

## Project docs

| Doc | Purpose |
|---|---|
| [AGENTS.md](AGENTS.md) | Rules for coding agents |
| [docs/ROADMAP.md](docs/ROADMAP.md) | 36-hour timeline, mid-eval cut line |
| [docs/PRD.md](docs/PRD.md) | Requirements and acceptance criteria |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | System design and data flow |
| [docs/VERIFICATION_PIPELINE.md](docs/VERIFICATION_PIPELINE.md) | Zero-guessing verification design |
| [docs/DATA_MODEL.md](docs/DATA_MODEL.md) | Schemas for chunks, claims, citations, reports |
| [docs/API_CONTRACT.md](docs/API_CONTRACT.md) | Backend API contract |
| [docs/DATASET_AND_EVAL.md](docs/DATASET_AND_EVAL.md) | Sample corpus and evaluation plan |
| [docs/DEMO_SCRIPT.md](docs/DEMO_SCRIPT.md) | Mid-eval and final demo scripts |
| [docs/AGENT_TASKS.md](docs/AGENT_TASKS.md) | Copy-paste tasks for coding agents |
| [docs/TECH_STACK.md](docs/TECH_STACK.md) | Stack choices and setup |

## Deliverables checklist

- [ ] Web app: live multi-document Q&A, side-by-side contradiction alerts, amendment tracking, safe abstention.
- [ ] Exact citations with document name, page number, verbatim quote.
- [ ] Faithfulness score shown in UI.
- [ ] Verification pipeline explanation (this README section + `docs/VERIFICATION_PIPELINE.md`).
- [ ] Models used documented in `docs/TECH_STACK.md`.
- [ ] Demo dataset in `data/samples/`.

## License

Hackathon prototype — add license as needed.