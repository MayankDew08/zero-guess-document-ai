# Tech Stack (Finalized)

All components are open-source. **No paid AI APIs.**

## Finalized stack

| Layer | Choice | Why | Fallback |
|---|---|---|---|
| Backend API | **FastAPI** + Uvicorn | Async, typed, OpenAPI docs | Flask |
| Frontend | **Vite + React + TypeScript + Tailwind** | Fast dev, custom evidence UI | Streamlit |
| PDF parsing | **PyMuPDF (`pymupdf`)** | Fast, page-aware, bboxes | pdfplumber for table-heavy pages |
| Chunk storage | **SQLite + JSON index files** | Simple, local, inspectable | JSON only |
| Embeddings | **`BAAI/bge-m3`** (`sentence-transformers`) | EN+HI, strong retrieval, local | Ollama `bge-m3` |
| Vector search | **numpy cosine / FAISS-ready interface** | Simple for hackathon corpus; interface allows swap | `faiss-cpu` |
| Keyword search | **rank-bm25** | Exact numbers/dates/terms | SQLite FTS5 |
| Reranker | **`BAAI/bge-reranker-v2-m3`** | EN+HI cross-encoder, CRAG gate | disable reranker, keep hybrid |
| LLM runtime | **Ollama** | Local model management | llama.cpp |
| LLM model | **`qwen2.5:7b-instruct`** | Good JSON instruction following | `qwen2.5:3b-instruct` |
| NLI / entailment | **`MoritzLaurer/mDeBERTa-v3-base-mnli-xnli`** | True 3-class NLI, multilingual | rule-based + abstain |
| Amendment graph | **networkx** | Simple DAG, inspectable | dict graph |
| PDF rendering | **pdfjs-dist** in frontend | Page render + bbox highlight | backend PNG |
| Reports | **JSON + HTML** | Inspectable, demo-friendly | Markdown |

## 16 GB RAM discipline

- Load HF models (`bge-reranker-v2-m3`, `mDeBERTa-v3-base-mnli-xnli`, and `bge-m3` when using sentence-transformers) as **lazy singletons**.
- Use `torch.float16` on CUDA/MPS where supported; clean CPU fallback.
- Never duplicate model instances in memory.
- Keep reranker/NLI batch sizes small (8/16).
- Tests use fake providers; real models are only loaded in runtime/smoke paths.

## Environment variables (`backend/.env.example`)

```env
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=qwen2.5:7b-instruct
OLLAMA_FALLBACK_MODEL=qwen2.5:3b-instruct
LLM_TEMPERATURE=0.1
LLM_MAX_TOKENS=1024
LLM_TIMEOUT_SECONDS=120

EMBEDDING_MODEL=BAAI/bge-m3
EMBEDDING_BACKEND=sentence-transformers
EMBEDDING_DEVICE=cpu

RERANKER_MODEL=BAAI/bge-reranker-v2-m3
RERANKER_TOP_K=12
RERANKER_KEEP_TOP_N=5
RERANK_ABSTAIN_THRESHOLD=0.25

NLI_MODEL=MoritzLaurer/mDeBERTa-v3-base-mnli-xnli
NLI_ENTAILMENT_THRESHOLD=0.65
NLI_CONTRADICTION_THRESHOLD=0.70
USE_FP16=true

CHUNK_TARGET_CHARS=450
CHUNK_OVERLAP_CHARS=80
HYBRID_TOP_K=12

DATA_DIR=../data
INDEX_DIR=../data/index
SAMPLE_DIR=../data/samples
REPORT_DIR=../data/reports

CORS_ORIGINS=http://localhost:5173,http://127.0.0.1:5173
LOG_LEVEL=INFO
```

## Python dependencies

See `backend/requirements.txt`. Key packages: `fastapi`, `uvicorn`, `pydantic`, `pymupdf`, `pdfplumber`, `rank-bm25`, `sentence-transformers`, `transformers`, `torch`, `numpy`, `networkx`, `sympy`, `httpx`, `python-dotenv`, `pytest`, `ruff`, `reportlab`.

## No-paid-API compliance checklist

- [x] No `openai`, `anthropic`, `google-generativeai`, `cohere`, `voyage` SDKs.
- [x] No API keys required except local Ollama URL.
- [x] Models are local/open-source.
- [x] App runs after model download without external AI calls.
- [x] README lists every model name and source.
