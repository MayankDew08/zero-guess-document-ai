# Demo Script — Mid-eval and Final

## Principles

- **Show the promise, not the plumbing.** Lead with verifiable answers, contradictions, amendment chain, abstention.
- **Pre-index everything.** No live ingestion delays during judging unless asked.
- **Keep a backup.** Screen recording + screenshots + cached API responses if Ollama misbehaves.
- **Abstention is a feature.** Say "it refuses to guess" confidently.

## Pre-demo checklist

- [ ] Ollama running; model loaded (`ollama run qwen2.5:7b-instruct "ok"`).
- [ ] Backend running on `:8000`, frontend on `:5173`.
- [ ] Sample corpus ingested and indexed.
- [ ] 5 scripted questions tested end-to-end.
- [ ] Browser tabs ready: app, one PDF open for visual reference (optional).
- [ ] Backup recording ready.

## Mid-eval demo (3 minutes, T+14h)

**Goal:** prove the core loop works.

### 0:00–0:20 — Setup
> "We built a zero-guessing Document AI. It answers only from verifiable evidence, cites verbatim quotes, and refuses to guess. Everything runs locally on open-source models — no paid APIs."

Show app with indexed docs.

### 0:20–1:20 — Supported multi-doc Q&A (M1, M2)
Ask:
> "What is the late payment fee according to the loan policy documents?"

Show:
- Answer with claims.
- Citation cards: document name, page number, verbatim quote.
- Click/expand one citation to show exact quote.

Say:
> "Every claim is tied to a document, page, and verbatim quote. We verify the quote exists in the source before showing it."

### 1:20–2:10 — Abstention (M5)
Ask:
> "What is the penalty for early loan closure?"

Show:
- "I don't have proof..." response.
- Missing evidence message.
- No fabricated citation.

Say:
> "When evidence is missing, it abstains instead of hallucinating."

### 2:10–2:50 — Faithfulness score (M6)
Point to faithfulness badge:
> "We compute faithfulness as the percentage of answer sentences backed by at least one verified source quote. This answer is 100% supported; the abstention is explicitly marked as no proof."

### 2:50–3:00 — What's next
> "By final demo we'll add side-by-side contradiction detection and amendment-chain resolution showing which rule applies today."

## Final demo (5-7 minutes, T+36h)

### 0:00–0:30 — Problem + promise
> "In banking, insurance, and policy teams, wrong answers are worse than no answers. Our system answers across multiple PDFs only when it can prove it — with exact citations, contradiction alerts, amendment tracking, and safe abstention. Fully local, open-source, no paid APIs."

### 0:30–1:30 — Multi-document Q&A with exact citations (M1, M2)
Ask a question spanning documents/pages.
Show:
- Answer.
- Each claim has citation: doc name, page, verbatim quote.
- Bonus if ready: click citation to highlight passage on rendered PDF page.

### 1:30–2:30 — Contradiction detection (M3)
Ask:
> "What is the service penalty for missing the SLA?"

Show:
- Contradiction alert.
- Side-by-side quotes: Contract A says INR 5,000, Contract B says INR 2,000.
- Clear "conflicting clauses" label.

Say:
> "Instead of picking one silently, it surfaces the conflict and shows both sources."

### 2:30–3:30 — Amendment chain (M4)
Ask:
> "Which late payment fee rule applies today?"

Show:
- Current rule: 2% per month (Amendment 2025).
- Chain: 2023 policy (1%) → 2024 amendment (1.5%) → 2025 amendment (2%).
- Citation/quote for each step.
- Effective dates.

Say:
> "It doesn't just retrieve the latest-looking text — it resolves the amendment chain and shows why this version applies."

### 3:30–4:30 — Zero-guessing abstention + faithfulness (M5, M6)
Ask an out-of-corpus question.
Show:
- "I don't have proof..." answer.
- Missing evidence.
- Faithfulness `N/A` or explicit abstention handling.
- Show a previous answered question with faithfulness `100% (4/4)`.

Say:
> "We verify every claim before display. If we can't prove it, we block it. Faithfulness is computed, not guessed."

### 4:30–5:30 — Verification pipeline / architecture (deliverable)
Show a simple diagram (README or slide):
> "Parse PDFs into page-aware chunks. Retrieve with embeddings plus keyword search. Draft structured claims with a local LLM. Verify every quote deterministically, check support, detect contradictions, resolve amendments, compute faithfulness, then render. Models: Qwen2.5 7B Instruct via Ollama for generation/verification, all-MiniLM-L6-v2 for embeddings — all local."

### 5:30–6:00 — Bonus (if implemented)
Pick one:
- **PDF highlight:** click citation, page renders with highlighted quote.
- **Hindi Q&A:** ask in Hindi, answer in Hindi, source quotes remain verbatim.
- **Calculation:** "Calculate penalty for 15 days delay..." show working with cited rate/fee values.

### 6:00–7:00 — Close / Q&A buffer
> "The key property is trust: every answer is auditable back to an exact quote, conflicts are visible, outdated rules are resolved, and missing evidence causes abstention instead of hallucination."

## Judge questions — prepared answers

| Question | Answer |
|---|---|
| "How do you prevent hallucinated citations?" | "Citations are verified deterministically: the quoted text must be a normalized substring of the cited chunk/page. If verification fails, the claim is blocked." |
| "What models do you use?" | "Open-source only: Qwen2.5-7B-Instruct via Ollama for drafting/verification, sentence-transformers all-MiniLM-L6-v2 for embeddings, FAISS for local vector search. Optional NLI cross-encoder for entailment." |
| "How is faithfulness calculated?" | "Supported answer sentences divided by total answer sentences, times 100. A sentence is supported only if it has at least one verified citation that passes support checks." |
| "What if documents conflict?" | "We detect same-subject conflicting values and show both quotes side by side. If an amendment chain resolves which version applies, we show the chain and current rule." |
| "What about scanned PDFs?" | "Current prototype targets digital PDFs. OCR can be added with Tesseract/PaddleOCR, but we scoped it out to guarantee citation integrity in 36 hours." |
| "Can it run offline?" | "Yes, after models are downloaded. No paid APIs, no external AI calls." |