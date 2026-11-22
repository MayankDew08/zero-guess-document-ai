# Verification Pipeline — Zero-Guessing

This is the core differentiator. The system must **verify before display**.

## Pipeline

```text
1. Ingest PDF -> chunks with doc/page/bbox/text + deterministic sentence spans (chunk_id#sN)
2. Index chunks -> bge-m3 embeddings + BM25; build amendment DAG
3. Retrieve top-k evidence (hybrid RRF, top 12)
4. Rerank with BAAI/bge-reranker-v2-m3 (keep top 5)
5. Gate 1 - CRAG: if max rerank score < RERANK_ABSTAIN_THRESHOLD -> abstain without LLM
6. Draft structured claims with source_ids only (qwen2.5:7b-instruct, JSON)
7. Gate 2 - Citation resolution: resolve source_ids to stored verbatim sentences/metadata
8. Gate 3 - NLI + numeric/date: mDeBERTa entailment AND numeric/date regex match
9. Amendment-aware contradiction detection
10. Gate 4 - Abstention: if 0 claims survive -> "I don't have proof..." + missing_evidence
11. Compute faithfulness_pct and blocked_claims_count; render verified response
```

## 1) Structured claim drafting

The LLM must not produce free-form final answers. It produces draft claims with `source_ids` only:

```json
{
  "claims": [
    {
      "claim_id": "c1",
      "text": "The late payment fee is 2% per month after the due date.",
      "claim_type": "factual",
      "source_ids": ["loan_v2_p3_c2#s0"]
    }
  ],
  "missing_evidence": []
}
```

**Prompt rules:**
- Use only provided chunks/sentences.
- 1 claim = 1 atomic sentence.
- Cite `source_ids` only (`chunk_id#sN`). Never free-type quotes.
- If evidence is missing, return empty/partial claims and describe `missing_evidence`.
- Output valid JSON only.

## 2) Gate 1 — CRAG pre-generation abstention

- After reranking, inspect `max_rerank_score`.
- If `max_rerank_score < RERANK_ABSTAIN_THRESHOLD` (default 0.25), **do not call the LLM**.
- Return `status="abstained"` with missing-evidence explanation.

## 3) Gate 2 — Deterministic source resolution

For each `source_id`:

1. Resolve `sentence_id` to a stored sentence span in a stored chunk.
2. Copy verbatim `text` as `quote`.
3. Copy `chunk_id`, `doc_id`, `doc_name`, `page`, and `bbox` from stored metadata.
4. If unresolved or malformed, block the claim with reason `unresolved_source_id`.

**Fail action:** unresolved/invalid `source_id` blocks the claim. Never fabricate a quote.

## 4) Gate 3 — NLI + numeric/date verification

A claim passes only if **both** checks pass:

### 4a. NLI entailment
- Model: `MoritzLaurer/mDeBERTa-v3-base-mnli-xnli`
- Input: `premise = resolved quote`, `hypothesis = claim text`
- Labels: `entailment`, `neutral`, `contradiction`
- Pass: `entailment` score >= `NLI_ENTAILMENT_THRESHOLD` and not contradicted.
- Fail: `contradiction` above threshold, or `neutral`/low entailment -> block.

### 4b. Deterministic numeric/date check
- Extract numbers, percentages, currencies, durations, and dates from claim and quote.
- Normalize formats (`2%`, `2 percent`, `INR 5,000`, `5000`, common date formats).
- Every numeric/date token in the claim must be present/matched in the cited quote context.
- Mismatch -> block with reason `numeric_or_date_mismatch`.

## 5) Amendment-aware contradiction detection

Contradictions are detected across evidence, not only within one claim.

1. Identify comparable subject/value pairs across retrieved docs.
2. **Consult amendment graph first.** If pair is explained by `AMENDS`/`SUPERSEDES`/`REPLACES` edge, route to Amendment Chain (resolved by newer effective date), not contradiction alert.
3. For unresolved pairs, run `mDeBERTa` NLI and numeric conflict checks.
4. If `contradiction` or incompatible numeric/date values for same subject, emit side-by-side Contradiction Alert with both verbatim quotes.

## 6) Gate 4 — Abstention

Abstain when:
- Gate 1 CRAG threshold not met.
- No relevant evidence retrieved.
- All draft claims fail Gate 2/3 verification.
- Evidence is contradictory and no amendment/precedence rule resolves it.
- Question asks for information outside corpus.

Response shape:

```json
{
  "status": "abstained",
  "answer": "I don't have proof in the provided documents to answer this question.",
  "missing_evidence": ["No clause mentioning early closure penalty was found in indexed documents."],
  "claims": [],
  "faithfulness_pct": null,
  "blocked_claims_count": 1
}
```

## 7) Faithfulness scoring

```python
supported = count of verified shown answer sentences/claims
total = count of shown answer sentences/claims
faithfulness_pct = round((supported / total) * 100, 1) if total > 0 else None
```

**Rules:**
- 1 claim = 1 atomic sentence, so claim-level and sentence-level faithfulness are identical.
- Compute over shown answer sentences/claims.
- Do not count blocked claims as supported.
- If abstaining fully, show `faithfulness_pct: null` (or N/A in UI); never 100% for empty answer.
- Return both `faithfulness_pct` and `blocked_claims_count` (plus blocked reasons in debug/details).

## 8) Logging for demo/debug

For every `/api/ask` call, store debug artifact:
- retrieved chunks + scores + rerank scores
- CRAG gate decision
- raw LLM draft
- source resolution decisions
- NLI/numeric verification decisions
- contradiction/amendment outputs
- final answer, faithfulness, blocked counts
