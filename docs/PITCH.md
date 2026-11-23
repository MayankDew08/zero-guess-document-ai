# Pitch: Zero-Guessing Document AI (Hackasol 5.0, Track 2, AIML-02)

Speaker cheat sheet. Numbers come from `data/reports/golden_eval_report.md`, the README benchmark, and our own runs. Config facts come from `backend/app/core/config.py`.

> Note: the README and AGENTS.md still say "RRF top 12 → rerank top 5". The current config is **hybrid top 20 → rerank keep 7** (`HYBRID_TOP_K=20`, `RERANKER_KEEP_TOP_N=7`). Say 20 → 7.

## 1. The 30-second hook

> "Document AI fails in three quiet ways: it guesses, documents contradict each other, and policies get amended so the old clause is still in the pile. We built a system where every claim must survive four deterministic gates before it is shown. Otherwise it blocks the claim or says 'I don't have proof.' It is fully local, with no paid API, and it measured 100% faithfulness and 100% quote exact-match on our benchmark. We will also show you where it fails."

## 2. The 3-minute walkthrough (7 slides)

| Slide | Say | Time |
|---|---|---|
| 1 Cover | Promise plus six numbers. "Everything on this slide was measured, not claimed." | 20 s |
| 2 Pipeline | Retrieve → Gate 1 relevance → draft → Gate 2 citations → Gate 3 NLI + numbers → Gate 4 lineage. **Key sentence: the LLM only returns sentence IDs, so it cannot invent a quote.** Code looks up the real text. | 40 s |
| 3 What judges see | The 2% vs 5% conflict side by side. v1 vs v3 is not flagged because the amendment chain explains it. Click a chip: the PDF page opens with the sentence highlighted. | 35 s |
| 4 Eight behaviours | Skim the table. Live demo: preset 1, preset 2, click a citation, preset 4 with the clarify form, then preset 6 (abstention). | 60 s |
| 5 Stack | Four open-source models, GPU/CPU split, runs on 6 GB VRAM and 16 GB RAM. | 20 s |
| 6 Measured | 100% / 100% / 100% / 0%, plus **leakage 3.6%** and the ablation. Own the weak numbers yourself. | 30 s |
| 7 Limits and tests | Live stage timings, the misses, 111 tests. Close: "Ask only what the corpus can prove." | 20 s |

## 3. Tech stack and why

| Layer | Choice | Why |
|---|---|---|
| Generator | `qwen2.5:7b-instruct` via Ollama (temp 0, JSON mode, 4096 ctx) | Fits a 6 GB GPU, good at structured JSON, handles Hindi, free and local. Fallback `qwen2.5:3b`. |
| Embeddings | `BAAI/bge-m3` | One multilingual model for English and Hindi. |
| Reranker | `BAAI/bge-reranker-v2-m3` | Same family and languages. Doubles as the relevance gate (threshold 0.25). |
| NLI | `MoritzLaurer/mDeBERTa-v3-base-mnli-xnli` | Real 3-class entailment, multilingual (XNLI covers Hindi). **Never use the reranker as an entailment proxy.** |
| Retrieval | BM25 + dense, RRF fusion | BM25 catches identifiers and amounts ("Circular No…", "₹750") that dense misses. |
| Parsing | pymupdf, sentence-level boxes, table rows | Boxes make the highlighted-PDF proof possible. |
| Lineage | networkx graph from regex clauses ("supersedes", "w.e.f.") | Deterministic and auditable. |
| Calculator | Python `Decimal` | No LLM arithmetic. |
| API | FastAPI, Pydantic schemas, SSE for live stages | SSE is one-way, simple, works over plain `fetch`. |
| UI | Vite + React 18 + TypeScript + Tailwind 3.4 | Hand-built components, no UI library. |
| Tests | pytest, 111 tests, injectable fake providers | Tests need no multi-GB model downloads. |

Design principle: verification is code wherever possible. There is no LLM-as-judge, because it is non-deterministic and unauditable.

## 4. Numbers and why they matter

| Metric | Result | Why it matters |
|---|---|---|
| Faithfulness | 100% (28/28) | Every shown sentence has a verified quote. High partly by construction: 36 drafted, **8 blocked**. |
| Independent leakage audit | 3.6% (1/28) | The honest number. A separate check, not our own gates. |
| Citation exact-match | 100% (30/30) | Quotes re-read from the PDF page with PyMuPDF. Proof the evidence is real. |
| Amendment resolution | 100% (12/12) | Picked the right active document. |
| Superseded false positives | 0/7 | Old-vs-new differences were not raised as conflicts. |
| Abstention accuracy | 90.9% (20/22) | Knowing when to refuse. 2/3 correct refusals, 1/18 false refusals. |
| Contradiction precision / recall | 71.4% / 100% | 5 true, 2 false flags. Hiding a conflict is worse than a false alarm. |
| Reranker MRR@5 | 0.897 vs 0.821 hybrid | Better ranking. Recall@5 tied with dense-only at 95.2%. |
| Latency | 16.3 s median, 28.7 s p95 | Three models on CPU plus the LLM. Measured running alone on the CPU. |

Retrieval ablation (21 questions, top 5): BM25 MRR 0.770 / Recall 90.5%; dense 0.853 / 95.2%; hybrid 0.821 / 92.9%; hybrid + reranker 0.897 / 95.2%.

Dataset: 24 hand-labelled cases (21 answerable for retrieval, 22 for end to end). Gold labels come from the PDFs, never from model output.

## 5. Questions the judge will ask

**"100% faithfulness on 28 sentences is a tiny sample, and it's your own metric."**
Agreed. n=28, and it is high partly because blocked claims never count. That is why we also report the independent audit (3.6% leakage) and abstention accuracy. Faithfulness means "backed by an entailing quote", not "correct".

**"Can a verified claim still be wrong?"**
Yes. GD-11 asked about home-loan interest and the system answered with the personal-loan 7% rate. The quote was real and NLI passed, but it answered the wrong question. That is our one leaked claim.

**"Hybrid scored lower recall than dense-only (92.9% vs 95.2%). Why hybrid?"**
On 21 questions that is one question, so it is noise-level. We kept hybrid for identifier and number queries. The real gain is ranking (MRR 0.897) after the reranker. **Gap to own: we did not ablate dense + reranker without BM25.** On the RBI corpus, hybrid recall (83.3%) was below dense (91.7%).

**"Gate 1 never fired in your eval. Is 0.25 useless?"**
It refused 0 of 3 no-proof questions before generation. The refusals came from Gates 2–4. Gate 1 is cost and latency protection; safety comes from the later gates. The threshold is configurable (`RERANK_ABSTAIN_THRESHOLD`).

**"Did you tune on your test set?"**
The golden set is a dev set. We found misses with it and fixed some. There is **no held-out test set**, the biggest methodological weakness. We report the remaining misses and did not tune them away.

**"NLI models are weak on long or multi-hop text."**
True. mDeBERTa-base judges one quote against one claim. That is why claims are atomic one-sentence statements and numbers and dates get a separate deterministic check. Multi-hop reasoning across pages is not supported; GD-18 (an RBI multi-page clause) was refused for that reason.

**"What about prompt injection inside a PDF?"**
Output is constrained to JSON claims with sentence IDs, and every claim must still be entailed by a stored quote. We have no dedicated injection filter, and a malicious quote could still be cited. Open risk.

**"Amendment detection by regex is brittle."**
It is regex over "supersedes", "amends", "w.e.f." and circular numbers: deterministic and auditable, but brittle on unusual phrasing. It worked on the real RBI circulars (12/12). An LLM fallback would add flexibility at the cost of auditability.

**"Does it scale?"**
Not as built. The index is in memory with brute-force cosine search and BM25. Fine for the demo (26 chunks) and our private test set (86 chunks); a real bank corpus needs an ANN index (FAISS or Qdrant). Scanned PDFs are unsupported (no OCR).

**"Why 16 seconds per answer?"**
The LLM plus three CPU-bound models. We built live stage streaming so users see progress. Next: a GPU reranker, quantised NLI, caching.

**"Is it deterministic?"**
Temperature is 0, but Ollama output still varies slightly (we saw 4 vs 5 drafted claims on the same question). The gates keep what is shown stable even when the draft varies.

**"Why local only?"**
Hackathon rule, and it fits banking: no data leaves the machine.

**"What did you build in the last stretch?"**
Workspaces (bank vs private), the zero-guessing chat layer, the golden benchmark, the audit UI, live stage streaming, and a full browser regression pass that found one real bug.

## 6. Things not to say

- Don't say "no hallucinations". Say "3.6% leakage in an independent audit, and here is the case."
- Don't call the benchmark a held-out test.
- Don't quote "top 12 → top 5". Say 20 → 7.
- Preset latencies on slide 4 come from the README's earlier run (`scripts/live_e2e.py`); don't present them as today's measurements.
