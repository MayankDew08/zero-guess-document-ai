# Agent Tasks — Copy-Paste Prompts for Coding Agents

Use these tasks with a decent coding agent (Claude Code, Cursor, Codex, DeepAI Code, etc.).  
Give the agent `AGENTS.md` context first. Execute tasks in order. Do not skip verification.

## How to use this file

1. Paste the **System/Context prompt** at the start of an agent session.
2. Run one task at a time. After each task, run its **Acceptance check**.
3. If a task fails, fix before moving on. Do not pile up broken foundations.
4. At mid-eval cut line (T+14h), only continue past Task 6 if Tasks 1-6 pass.

---

## System / Context prompt

```text
You are building a 36-hour hackathon prototype: "Zero-Guessing & Contradiction-Checking Document AI" (Hackasol 5.0, AIML-02, Option B).

Read these files before coding:
- AGENTS.md
- docs/PRD.md
- docs/ARCHITECTURE.md
- docs/VERIFICATION_PIPELINE.md
- docs/DATA_MODEL.md
- docs/API_CONTRACT.md

Hard constraints:
- No paid/external AI APIs. Local open-source models only.
- Every displayed claim must cite document name, page number, and verbatim quote.
- Verify quotes deterministically before display. Never invent citations.
- If evidence is missing/contradicted/unsupported, abstain and state what evidence is missing.
- Faithfulness score = supported answer sentences / total answer sentences * 100.

Stack: FastAPI + Python backend, Vite + React + TS + Tailwind frontend, PyMuPDF, sentence-transformers/all-MiniLM-L6-v2, FAISS, rank-bm25, Ollama with qwen2.5:7b-instruct.

Work in small steps. Add tests for verification logic. Keep code simple and inspectable.
```

---

## Task 1 — Scaffold repo and backend skeleton

```text
Task 1: Scaffold repo and backend skeleton.

Create this structure:
- backend/app/main.py (FastAPI app, CORS, /api/health)
- backend/app/api/routes_health.py
- backend/app/models/schemas.py (Pydantic models from docs/DATA_MODEL.md)
- backend/app/core/config.py (env settings from docs/TECH_STACK.md)
- backend/requirements.txt
- backend/.env.example
- frontend/ (Vite React TS Tailwind scaffold)
- data/samples/.gitkeep
- data/index/.gitkeep
- scripts/.gitkeep

Implement GET /api/health returning status, ollama connectivity check, model name, indexed_docs/chunks counts.
Add backend README/run instructions to root README if missing.

Acceptance check:
- `cd backend && uvicorn app.main:app --reload --port 8000` starts.
- `curl http://localhost:8000/api/health` returns JSON.
- `cd frontend && npm run dev` starts.
```

## Task 2 — PDF ingestion and chunking

```text
Task 2: Implement PDF ingestion and chunking.

Files:
- backend/app/ingestion/parser.py
- backend/app/ingestion/chunker.py
- backend/app/ingestion/store.py
- backend/app/api/routes_ingest.py

Requirements:
- Parse PDFs with PyMuPDF.
- Extract page-aware blocks with text and bbox where possible.
- Create chunks with: chunk_id, doc_id, doc_name, page, section?, text, normalized_text, chunk_type, bbox?.
- Chunk target ~450 chars with ~80 overlap, but do not split mid-sentence if easy.
- Handle table-like pages as chunk_type="table" with best-effort extracted text.
- Store chunks to data/index/chunks.json (or SQLite) and documents metadata.
- POST /api/ingest accepts multipart PDF files or use_samples=true.
- GET /api/documents lists indexed docs.

Acceptance check:
- Ingest 2 sample PDFs.
- chunks.json contains entries with correct doc_name and page numbers.
- Every chunk has non-empty text and chunk_id.
- `pytest -q` passes any parser unit tests you add.
```

## Task 3 — Embeddings and retrieval

```text
Task 3: Implement hybrid retrieval.

Files:
- backend/app/retrieval/embeddings.py
- backend/app/retrieval/vector_store.py
- backend/app/retrieval/bm25_store.py
- backend/app/retrieval/retriever.py
- backend/app/api/routes_retrieve.py (optional debug endpoint)

Requirements:
- Use sentence-transformers/all-MiniLM-L6-v2 for embeddings.
- Build FAISS index over chunks; persist to data/index/faiss.index + id map.
- Build BM25 index over normalized chunk text.
- Retriever merges semantic and BM25 results, dedupes by chunk_id, returns top_k RetrievedChunk objects.
- Expose debug endpoint POST /api/retrieve {query, top_k} returning retrieved chunks and scores.

Acceptance check:
- After ingest, querying "late payment fee" returns chunks containing that phrase or semantically relevant chunks.
- Retrieval returns doc_name/page/chunk_id for every result.
- Rebuilding index from stored chunks works.
```

## Task 4 — Structured Q&A with citations

```text
Task 4: Implement Q&A draft generation with structured citations.

Files:
- backend/app/qa/prompt.py
- backend/app/qa/llm.py (Ollama client)
- backend/app/qa/draft.py
- backend/app/api/routes_ask.py (initial version)

Requirements:
- Use Ollama local model from env (default qwen2.5:7b-instruct).
- Prompt LLM to answer using ONLY provided chunks.
- LLM output must be JSON with claims. Each claim has `text`, `claim_type`, and `source_ids` only — citing `chunk_id#sN` values. Never free-type quotes.
- The backend resolves `source_ids` to verbatim `quote`, `doc_name`, `page`, `bbox` from stored chunks.
- If evidence missing, LLM should return `missing_evidence` with descriptions, no quoted text.
- Parse/validate JSON with Pydantic; retry once with repair prompt if malformed. Max 2 attempts; if still failing, return `status=abstained` with debug reason.
- /api/ask runs draft + full verification; response status reflects verified final answer, not draft.

Acceptance check:
- Ask a supported question over sample corpus; response contains claims with source_ids only; backend resolves citations and shows verbatim quotes with doc/page.
- Ask an unsupported question; response indicates abstention/missing evidence; no fabricated citations.
- Invalid LLM JSON after retry does not crash server; safe abstention occurs.
```

## Task 5 — Deterministic verification and faithfulness

```text
Task 5: Implement verification pipeline and faithfulness scoring.

Files:
- backend/app/verification/quote_check.py
- backend/app/verification/support_check.py
- backend/app/verification/numeric_check.py
- backend/app/verification/verifier.py
- backend/app/scoring/faithfulness.py
- backend/tests/test_verification.py

Requirements:
- Source resolution: LLM cites `source_ids` (`chunk_id#sN`); backend resolves verbatim quote/doc/page/bbox from stored chunks. Unresolved source_id blocks the claim.
- Quote check: normalized resolved quote must be substring of cited chunk/sentence text. If not, citation fails.
- Metadata check: chunk_id/doc/page must resolve to indexed chunk and match stored metadata.
- Support check: at minimum rule-based numeric/date match; optionally NLI/LLM verifier. Unsupported claims blocked.
- Faithfulness: supported_answer_sentences / total_answer_sentences * 100.
- /api/ask must run verification before returning response. No unverified quote shown as verified.
- Abstain when no claims pass verification.

Acceptance check:
- Unit tests cover: exact quote pass, whitespace-normalized pass, fabricated quote fail, wrong number fail.
- /api/ask never returns a citation quote that is absent from the cited chunk.
- Faithfulness score is present and correct on a simple fixture.
```

## Task 6 — Frontend MVP for mid-eval

```text
Task 6: Build frontend MVP.

Files:
- frontend/src/App.tsx
- frontend/src/api/client.ts
- frontend/src/components/UploadPanel.tsx
- frontend/src/components/QuestionBox.tsx
- frontend/src/components/AnswerPanel.tsx
- frontend/src/components/CitationCard.tsx
- frontend/src/components/FaithfulnessBadge.tsx
- frontend/src/components/AbstentionBanner.tsx

Requirements:
- Upload/select sample PDFs and trigger ingest.
- Ask question and render response.
- Show answer, claims, citation cards (doc name, page, verbatim quote).
- Show faithfulness badge.
- Show abstention banner when status=abstained.
- Handle loading/error states clearly.

Acceptance check:
- User can ingest sample PDFs and ask a question from browser.
- Supported answer shows citations and faithfulness.
- Abstained answer shows clear "no proof / missing evidence" state.
- Mid-eval demo script can be performed without terminal.
```

**Mid-eval cut line: Tasks 1-6 must pass before moving on.**

## Task 7 — Contradiction detection

```text
Task 7: Implement contradiction detection.

Files:
- backend/app/contradictions/detector.py
- backend/app/contradictions/extractor.py
- backend/tests/test_contradictions.py
- frontend/src/components/ContradictionCard.tsx

Requirements:
- Detect conflicting numbers/dates/rules/eligibility for same subject across retrieved chunks/docs.
- Start with deterministic numeric/date/percentage extraction and comparison.
- Use LLM/NLI only as secondary classifier if needed.
- Return Contradiction objects with subject, conflict_type, explanation, two+ values with doc/page/quote.
- UI shows side-by-side quotes.

Acceptance check:
- Planted corpus with conflicting penalty values produces contradiction.
- Both quotes are displayed side by side with doc/page.
- No contradiction for identical values.
```

## Task 8 — Amendment chain resolution

```text
Task 8: Implement amendment chain detection and resolution.

Files:
- backend/app/amendments/parser.py
- backend/app/amendments/graph.py
- backend/app/amendments/resolver.py
- backend/tests/test_amendments.py
- frontend/src/components/AmendmentChain.tsx

Requirements:
- Detect amendment cues: amends, supersedes, replaces, revised, effective from/date.
- Extract edges with evidence quotes and effective dates where possible.
- Build graph and resolve current applicable rule for a subject/question.
- Return chain A->B->C and current rule with citations.
- UI shows chain/timeline and highlights current rule.

Acceptance check:
- 3-doc planted amendment corpus resolves latest rule correctly.
- Chain shows all three docs with evidence quotes.
- Ambiguous/missing date case returns status ambiguous/unresolved with evidence, not a confident wrong answer.
```

## Task 9 — Report generation and hardening

```text
Task 9: Add report generation and harden error handling.

Files:
- backend/app/scoring/report.py
- backend/app/api/routes_report.py
- frontend/src/components/ReportButton.tsx
- backend/tests/test_api_ask.py

Requirements:
- Generate HTML report containing question, answer, claims, citations, contradictions, amendment chain, faithfulness, missing evidence.
- Endpoint POST /api/report and GET /api/reports/{id}/download.
- Handle Ollama down, empty index, bad PDF, malformed LLM output, no retrieval results.
- Add request_id to responses and logs.

Acceptance check:
- Report downloads/opens and includes citations and faithfulness.
- Out-of-corpus question returns abstained response, not 500.
- Malformed model output results in safe abstention/retry, not crash.
```

## Task 10 — Bonus (pick one only if M1-M6 pass)

```text
Task 10 (bonus, pick ONE):

Option B1 - PDF highlight:
- Add GET /api/documents/{doc_id}/pages/{page}/image or render PDF.js in frontend.
- Use bbox metadata from chunks/citations to overlay highlight.
- Clicking a citation scrolls to page and highlights quote.

Option B2 - Hindi Q&A:
- Accept Hindi questions.
- Retrieve against English corpus (translate query to English for retrieval if needed, locally).
- Return answer in Hindi if question is Hindi; keep source quotes verbatim in original language.
- Clearly label translated answer.

Option B3 - Clause calculation:
- Detect calculation questions (penalty/EMI/interest from stated values).
- Extract numeric inputs from cited clauses.
- Show formula, substitution, result, and citation for each input value.
- Verify calculated output against extracted inputs.

Acceptance check:
- One prepared bonus case works end-to-end.
- Core M1-M6 demo still passes after bonus.
```

---

## Debug prompts for agents

### When citations are hallucinated
```text
Debug: /api/ask returns quotes not found in source.
Inspect verification/quote_check.py. Ensure normalize_text collapses whitespace and compare against chunk.text.
Add test with fabricated quote. Block any citation where normalized quote is not substring of normalized chunk text.
Do not display unverified citations.
```

### When LLM returns bad JSON
```text
Debug: Ollama model returns non-JSON or wrong schema.
Wrap LLM call in parse_retry: attempt json.loads + Pydantic validation; on failure send repair prompt with the bad output and schema; max 2 attempts; if still failing return abstained response with debug reason.
Add test using mocked LLM response.
```

### When retrieval misses obvious evidence
```text
Debug: Retrieval misses known clause.
Check chunking boundaries, embedding model loaded once, FAISS index built after ingest, BM25 tokenization.
Add hybrid merge: take top_k semantic + top_k bm25, dedupe, rerank by combined score.
Add debug endpoint /api/retrieve to inspect scores.
```

### When contradiction detection is noisy
```text
Debug: Contradiction detector flags non-conflicts.
Narrow detection to same subject and comparable value type. Require numeric/date/rule value mismatch, not just different wording.
Mark uncertain cases as status="possible" with lower severity; only show confirmed when values clearly conflict.
Add tests for false positive cases.
```
