# PRD — Zero-Guessing & Contradiction-Checking Document AI

## Problem

Teams in banking, insurance, and public policy rely on dense PDFs. Standard chatbots miss answers split across pages, overlook conflicting clauses, and invent details when evidence is missing. Many organizations cannot send confidential documents to external AI services.

## Product goal

Build a working prototype that answers complex questions across multiple PDFs using **only exact, verifiable evidence**. It must resolve which rule version applies, highlight contradictions, and refuse to guess when proof is missing. The whole pipeline must run on **open-source models without any paid AI API**.

## Users

| User | Need | Success signal |
|---|---|---|
| Investigator / analyst | Find answer across many PDFs quickly | Gets answer with clickable citations |
| Compliance / legal reviewer | Detect conflicting or outdated clauses | Sees contradictions and amendment chain clearly |
| Risk-averse org | Avoid hallucinated AI output | System abstains and shows missing evidence |

## Scope

### Must-have (hackathon scoring)

| ID | Requirement | Acceptance criteria | Demo check |
|---|---|---|---|
| M1 | **Multi-document evidence retrieval** | Parse and search across several PDFs, including tables and multi-page sections; combine evidence for one question. | Ask a question whose answer spans 2 docs or 2 pages; answer cites both. |
| M2 | **Exact citations** | Every claim in answer links to document name, page number, and verbatim quote that supports it. | Click/inspect any claim; quote is found verbatim on cited page. |
| M3 | **Contradiction detection** | Flag conflicting numbers, dates, rules, or eligibility conditions for same subject; show both quotes side by side. | Contradiction card shows Doc A quote vs Doc B quote with fields highlighted. |
| M4 | **Amendment chains** | When C amends B amends A, determine which rule applies today and show chain of changes. | "Which rule applies today?" returns current rule + A→B→C chain with dates. |
| M5 | **Zero-guessing abstention** | Verify each claim before showing. Unsupported/contradicted claim blocked; system states clearly what evidence is missing. | Out-of-corpus question returns "I don't have proof..." and missing evidence. |
| M6 | **Faithfulness score** | Show share of answer sentences backed by >=1 matching source quote, as percentage. | UI displays e.g. "Faithfulness: 100% (4/4 sentences supported)". |

### Bonus (only after M1-M6 stable)

| ID | Requirement | Acceptance criteria |
|---|---|---|
| B1 | PDF passage highlight | Clicking citation highlights quoted passage on rendered PDF page. |
| B2 | Hindi Q&A | User can ask/receive answer in Hindi; citations remain verbatim source quotes. |
| B3 | Clause calculation | Questions requiring calculation (penalty/EMI from rate and fee table) show working and cite clause values. |

### Non-goals (for 36h)

- Production auth/multi-tenant document permissions.
- OCR for scanned PDFs (unless time remains; assume digital PDFs).
- Fine-tuning models.
- Perfect legal reasoning. The system must be *verifiable*, not omniscient.
- Paid APIs, hosted vector DBs, or proprietary models.

## User flows

### Flow 1 — Upload and ask
1. User uploads/selects PDFs.
2. System ingests, chunks, indexes.
3. User asks question.
4. System retrieves evidence, drafts claims, verifies, renders answer with citations and faithfulness score.

### Flow 2 — Contradiction
1. User asks about a value/rule present in conflicting docs.
2. System detects conflict during retrieval/verification.
3. UI shows answer with contradiction alert: two quotes side by side, conflict field, docs/pages.

### Flow 3 — Amendment chain
1. User asks "What is the current late fee / which rule applies today?"
2. System identifies amendment relations and effective dates.
3. UI shows current applicable rule, chain A→B→C, and citations for each step.

### Flow 4 — Abstention
1. User asks question not supported by corpus.
2. Retrieval finds weak/no evidence, or verification blocks claims.
3. UI shows: "I don't have proof." + what was searched + what evidence is missing.

## Quality bar

- **Citation integrity:** 100% of displayed quotes must be verifiably present in cited source page/chunk.
- **No forced answer:** If evidence is insufficient, abstention is correct behavior.
- **Visible reasoning:** Contradictions and amendment chains show the underlying quotes/dates, not just a conclusion.
- **Deterministic scoring:** Faithfulness score computed by code from verified claim-sentence mapping.

## Risks and mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| Local LLM hallucinated citations | Breaks core promise | Structured output + deterministic quote verification; block unverified claims. |
| PDF table extraction poor | Misses evidence | PyMuPDF + table-aware chunking; keep raw text fallback; test with table-heavy samples. |
| Amendment detection brittle | Wrong "current rule" | Combine explicit phrase patterns + effective dates + LLM extraction; show chain evidence. |
| Contradiction false positives | Noisy UI | Require same subject/field + conflicting values; show as "possible contradiction" if uncertain. |
| 7B model slow on CPU | Bad demo | Preload model, cache embeddings, keep top-k small, have smaller fallback model. |
| Team overbuilds bonus | Miss must-haves | Follow roadmap cut lines; no bonus before M1-M6 demo pass. |

## Demo success criteria

By mid-eval (T+14h): M1, M2, M5, M6 minimally working on sample corpus.  
By final (T+36h): M1-M6 working end-to-end in web UI; contradiction and amendment shown on prepared corpus; README explains verification pipeline and models.