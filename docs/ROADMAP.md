# Roadmap — 36-Hour Hackathon Plan

## Time anchors

**Start:** Day 1, 20:00 (**T+0**)  
**Mid-eval:** Day 2, 10:00 (**T+14h**)  
**End:** Day 3, 08:00 (**T+36h**)

> **Rule:** No bonus work before M1-M6 demo path is stable. If behind schedule, cut scope, not verification.

## Milestone summary

| Milestone | Deadline | What must be true |
|---|---:|---|
| M0 — Scaffold | T+2h (22:00 D1) | Repo runs, Ollama/model pulled, sample PDFs loaded |
| M1 — Retrieval + citations | T+8h (04:00 D2) | Question over 2 PDFs returns answer with doc/page/verbatim quotes |
| M2 — Mid-eval slice | T+14h (10:00 D2) | M1 + abstention + faithfulness score visible in basic UI/CLI |
| M3 — Contradictions + amendments | T+22h (18:00 D2) | Side-by-side contradictions and A→B→C amendment chain working |
| M4 — Final polish | T+34h (06:00 D3) | M1-M6 stable, report/export, README/diagram, demo rehearsed |
| M5 — Submission | T+36h (08:00 D3) | Clean repo, runnable demo, backup video/screenshots |

## Detailed schedule

### Phase 0 — Setup (T+0 to T+2h)

**Owner:** everyone

- [ ] Assign roles: Backend/Pipeline, Verification/Logic, Frontend/Demo, Dataset/Eval (roles can overlap in small team).
- [ ] Create repo layout per `AGENTS.md`.
- [ ] Install Python deps, Node deps, Ollama; pull `qwen2.5:7b-instruct` and embedding model.
- [ ] Add 3-5 sample digital PDFs to `data/samples/`.
- [ ] Confirm `GET /api/health` and frontend dev server run.

**Exit criteria:** `uvicorn` serves health; `npm run dev` serves UI; Ollama responds locally.

### Phase 1 — Ingestion & retrieval (T+2h to T+8h)

**Owner:** Backend/Pipeline

- [ ] PDF parsing with PyMuPDF: page text, blocks, bbox where available.
- [ ] Chunking: 300-500 token/char target, page/section metadata preserved.
- [ ] Deterministic sentence spans per chunk (`chunk_id#sN`) for citation resolution.
- [ ] Embeddings with `all-MiniLM-L6-v2`; FAISS index.
- [ ] BM25 index over normalized chunk text.
- [ ] Hybrid retriever: merge semantic + BM25, dedupe by `chunk_id`, return top-k.
- [ ] `POST /api/ingest` and `GET /api/documents`.

**Exit criteria:** indexing sample PDFs produces searchable chunks with `doc_name`, `page`, `text`, `chunk_id`, and sentence IDs.

**Cut line:** if table extraction is messy, store page text blocks and mark TODO; do not block retrieval.

### Phase 2 — Q&A with verified citations (T+8h to T+12h)

**Owner:** Backend/Pipeline + Verification

- [ ] `/api/ask` endpoint: retrieve -> draft claims -> verify -> respond.
- [ ] LLM prompt returns structured JSON claims with `source_ids` only (no free-typed quotes).
- [ ] Backend resolves `source_ids` to verbatim quotes and metadata from stored chunks.
- [ ] Deterministic quote verifier: normalized substring match against cited chunk.
- [ ] Support check: simple rule-based checks; optional NLI/LLM verifier if time allows.
- [ ] Block claims with failed verification; do not display fabricated citations.

**Exit criteria:** a supported question returns claims with verifiable doc/page/quote citations.

### Phase 3 — Abstention + faithfulness + basic UI (T+12h to T+14h, mid-eval)

**Owner:** Frontend/Demo + Verification

- [ ] Faithfulness scorer: supported shown sentences / total shown sentences.
- [ ] Return `faithfulness_pct` and `blocked_claims_count`.
- [ ] Abstention response: "I don't have proof..." + missing evidence.
- [ ] Minimal UI: upload/select docs, question box, answer, citations, faithfulness badge, abstention banner.
- [ ] Prepare 3-question mid-eval script.

**Mid-eval demo must show:** M1 + M2 + M5 + M6 (minimum viable version).

**Cut line:** if UI is behind, demo from CLI/Swagger but still show exact citations and faithfulness.

### Phase 4 — Contradictions (T+14h to T+18h)

**Owner:** Verification/Logic

- [ ] Subject/field extraction heuristics (fee, date, age, percentage, amount).
- [ ] Consult amendment graph first: if conflict is explained by `AMENDS`/`SUPERSEDES`, route to amendment chain.
- [ ] Compare values across retrieved docs/chunks for unresolved same-subject conflicts.
- [ ] Emit contradiction object with both quotes, doc/page, explanation.
- [ ] UI: contradiction card with side-by-side quotes.

**Exit criteria:** planted conflicting docs produce a clear contradiction alert.

### Phase 5 — Amendment chains (T+18h to T+22h)

**Owner:** Verification/Logic

- [ ] Detect amendment cues: "amends", "supersedes", "replaces", "effective from".
- [ ] Build simple amendment graph in memory/JSON.
- [ ] Resolve current rule by effective date or latest amendment.
- [ ] Return chain with evidence quotes for each edge/node.
- [ ] UI: timeline/chain view + "current rule applies" highlight.

**Exit criteria:** 3-doc A→B→C sample resolves current rule correctly with citations.

**Cut line:** if automatic graph is brittle, allow a precomputed amendment metadata file for demo corpus but keep evidence quotes real.

### Phase 6 — Polish, report, demo (T+22h to T+34h)

**Owner:** everyone

- [ ] HTML/PDF report generation for a Q&A session.
- [ ] Error handling: no docs, Ollama down, bad PDF, invalid JSON.
- [ ] Performance: preload models, cache embeddings/index.
- [ ] README with setup, architecture diagram, models, no-paid-API statement.
- [ ] Build planted demo corpus: contradiction, amendment chain, abstention case.
- [ ] Rehearse 5-minute demo twice.

**Bonus only if stable:** PDF highlight (B1), Hindi Q&A (B2), clause calculation (B3).

### Phase 7 — Submission buffer (T+34h to T+36h)

- [ ] Freeze main branch / demo commit.
- [ ] Verify fresh clone setup steps.
- [ ] Record backup demo video.
- [ ] Submit repo + demo materials.

## Ownership map (adapt to team size)

| Area | Primary | Backup |
|---|---|---|
| PDF ingestion, chunking, indexing | Backend | Verification |
| Retrieval, LLM prompting, JSON schema | Backend | Frontend |
| Quote verification, faithfulness, abstention | Verification | Backend |
| Contradiction/amendment logic | Verification | Backend |
| React UI, citations, score, demo polish | Frontend | Backend |
| Sample corpus, gold QAs, eval script, README | Dataset/Eval | everyone |

## Risk register

| Risk | Likelihood | Impact | Trigger | Mitigation |
|---|---:|---:|---|---|
| Ollama/model too slow | Med | High | >20s per answer | Use 3B fallback, smaller top-k, cache retrieval |
| LLM outputs bad JSON | High | Med | parse errors | strict schema + repair retry + safe abstain |
| Citations hallucinated | Med | Critical | quote not in source | deterministic quote verifier blocks display |
| PDF parsing inconsistent | Med | Med | missing text/bboxes | PyMuPDF block fallback, test sample corpus early |
| Amendment logic wrong | Med | High | wrong "current rule" | show evidence chain; use explicit dates; fallback metadata |
| Scope creep | High | High | bonus work before M6 | enforce cut lines; daily scope check |

## Definition of done (final)

- [ ] M1-M6 acceptance criteria pass on demo corpus.
- [ ] No unverified quote displayed in UI.
- [ ] Faithfulness score visible and computed by code.
- [ ] Contradiction and amendment demo cases reproducible.
- [ ] README explains setup, architecture, models, and no-paid-API compliance.
- [ ] Fresh run works after following README.