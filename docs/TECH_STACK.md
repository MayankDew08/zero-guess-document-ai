# Tech Stack (Locked for 36h)

All components are open-source. **No paid AI APIs.**

## Recommended stack

| Layer | Choice | Why | Fallback |
|---|---|---|---|
| Backend API | **FastAPI** + Uvicorn | Fast to build, async, OpenAPI docs | Flask |
| Frontend | **Vite + React + TypeScript + Tailwind** | Fast dev, easy custom UI for citations/contradictions | Streamlit (faster but less control) |
| PDF parsing | **PyMuPDF (`pymupdf`)** | Fast, page-aware, text blocks and bboxes for highlighting | pdfplumber for table-heavy pages |
| Chunk storage | **SQLite** or JSON files | Simple, local, inspectable | In-memory dict for MVP |
| Embeddings | **`sentence-transformers/all-MiniLM-L6-v2`** | Small, CPU-friendly, good enough for hackathon | `BAAI/bge-small-en-v1.5`, Ollama `nomic-embed-text` |
| Vector search | **FAISS (`faiss-cpu`)** | Local, fast, easy | ChromaDB, or numpy cosine similarity for tiny corpus |
| Keyword search | **rank-bm25** | Catches exact numbers/dates/terms embeddings miss | SQLite FTS5 |
| LLM runtime | **Ollama** | Easy local model management, local REST API | llama.cpp, transformers+bitsandbytes |
| LLM model | **`qwen2.5:7b-instruct`** (default) | Good instruction/JSON following, fits ~6-8GB quantized | `qwen2.5:3b-instruct`, `llama3.2:3b`, `phi3:mini` |
| NLI / entailment | **Optional:** `cross-encoder/nli-deberta-v3-base` or LLM verifier prompt | Lightweight entailment/contradiction signal | Rule-based + LLM verifier only |
| PDF rendering | **PDF.js** in frontend | Highlight cited passage on page (bonus) | Render page image via PyMuPDF |
| Reports | **HTML report** | Simple, includes quotes and scores | Markdown export, browser print-to-PDF |

## Hardware guidance

| Setup | What works | Notes |
|---|---|---|
| 16GB RAM, no GPU | 3B quantized LLM + MiniLM embeddings | Slow generation; keep prompts short, top-k small. |
| 16GB RAM + 6-8GB GPU | 7B Q4 quantized via Ollama | Good demo sweet spot. |
| 32GB+ RAM / 12GB+ GPU | 7B-14B comfortably | Best quality; not required. |

## Environment variables (`backend/.env.example`)

```env
# LLM
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=qwen2.5:7b-instruct
LLM_TEMPERATURE=0.1
LLM_MAX_TOKENS=1024

# Embeddings
EMBEDDING_MODEL=sentence-transformers/all-MiniLM-L6-v2
EMBEDDING_DEVICE=cpu   # or cuda

# Retrieval
CHUNK_SIZE=450
CHUNK_OVERLAP=80
TOP_K_RETRIEVAL=8

# Storage
DATA_DIR=../data
INDEX_DIR=../data/index
SAMPLE_DIR=../data/samples
REPORT_DIR=../data/reports

# Verification
MIN_QUOTE_MATCH_SCORE=0.95
```

## Python dependencies (baseline)

```txt
fastapi>=0.111.0
uvicorn[standard]>=0.30.0
pydantic>=2.7.0
python-multipart>=0.0.9
pymupdf>=1.24.0
sentence-transformers>=3.0.0
faiss-cpu>=1.8.0
rank-bm25>=0.2.2
numpy>=1.26.0
httpx>=0.27.0
python-dotenv>=1.0.1
pytest>=8.2.0
ruff>=0.5.0
```

Optional:
```txt
pdfplumber>=0.11.0        # table extraction fallback
transformers>=4.42.0       # optional local NLI cross-encoder
torch>=2.3.0               # required by transformers/sentence-transformers
weasyprint>=62.0           # HTML->PDF reports
```

## Frontend dependencies (baseline)

```bash
npm create vite@latest frontend -- --template react-ts
cd frontend
npm install
npm install -D tailwindcss postcss autoprefixer
npm install react-pdf pdfjs-dist        # bonus: PDF highlight
npm install lucide-react                # icons
```

## Model choices and rationale

### LLM — `qwen2.5:7b-instruct`
- Good at following "answer only from context" instructions.
- Decent JSON-structured output with prompting.
- Runs locally via Ollama; no API key.
- **Rule:** temperature low (0-0.2) for verifiable answers.

### Embeddings — `all-MiniLM-L6-v2`
- 384 dims, fast on CPU, simple `sentence-transformers` API.
- Good enough for semantic retrieval over hackathon corpus.
- **Rule:** same model for indexing and query.

### NLI — optional
- A small cross-encoder (e.g., `cross-encoder/nli-deberta-v3-base`) can assist entailment/contradiction checks.
- Not required if time is tight; LLM verifier prompt + deterministic checks are acceptable.
- **Rule:** NLI assists verification; deterministic quote/number checks still required.

## No-paid-API compliance checklist

- [ ] No `openai`, `anthropic`, `google-generativeai`, `cohere` SDKs in requirements.
- [ ] No API keys required except local Ollama URL.
- [ ] App runs with network disabled after model download (stretch goal).
- [ ] README lists every model name and source.
