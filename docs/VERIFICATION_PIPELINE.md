# Verification Pipeline — Zero-Guessing

This is the core differentiator. The system must **verify before display**.

## Pipeline

```text
1. Ingest PDF -> chunks with doc/page/bbox/text + deterministic sentence spans
2. Index chunks -> FAISS + BM25
3. Retrieve top-k evidence for question
4. Draft structured claims with source_ids (local LLM, JSON only)
5. Resolve source_ids -> verbatim quotes/metadata from stored chunks (deterministic)
6. Verify each claim
   - source_id resolves to stored sentence/chunk?
   - quote appears verbatim in cited chunk (normalized whitespace)?
   - metadata matches stored chunk?
   - evidence entails/supports claim? (rule-based / optional NLI / LLM verifier)
   - numbers/dates match?
7. Detect contradictions (amendment-aware)
8. Resolve amendment chain if question touches amended rule
9. Compute faithfulness score and blocked_claims_count
10. Abstain/block unsupported claims
11. Render verified response
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

## 2) Source resolution (deterministic)

For each `source_id`:

1. Resolve `sentence_id` to a stored sentence span in a stored chunk.
2. Copy verbatim `text` as `quote`.
3. Copy `chunk_id`, `doc_name`, `page`, and `bbox` from stored metadata.
4. If unresolved, block the claim with reason `unresolved_source_id`.

**Fail action:** unresolved or invalid `source_id` blocks the claim. Never fabricate a quote.

```python
def normalize(s: str) -> str:
    return " ".join(s.replace("\u00a0", " ").split()).strip().casefold()
```

## 3) Quote verification (deterministic)

For each resolved citation:

1. Resolve `chunk_id` to stored chunk.
2. Normalize both stored chunk/sentence text and quote.
3. Check quote is a normalized substring/equal span of the stored text.
4. Verify cited `doc_name` and `page` match the stored chunk.

**Pass condition:** exact/normalized match against stored text.

**Fail action:** block citation; if claim has no verified citation, block claim.

## 4) Support verification

A quote existing is necessary but not sufficient. The claim must be supported by the quote.

**Methods (use in order as needed):**
1. **Rule-based:** for simple numeric/date claims, extract values and compare.
2. **Optional NLI model:** e.g., `cross-encoder/nli-deberta-v3-base` for entailment/contradiction/neutral.
3. **LLM verifier prompt:** ask local LLM to label `SUPPORTED | CONTRADICTED | NOT_ENOUGH_INFO` with reason.

**Pass condition:** SUPPORTED/ENTAILMENT.  
**Fail action:** CONTRADICTED -> contradiction candidate + block; NOT_ENOUGH_INFO -> abstain/block.

## 5) Numeric/date verification (deterministic)

Extract numbers, percentages, currency, dates, durations from claim and quote.

| Claim | Quote | Result |
|---|---|---|
| "2% per month" | "2% per month applies..." | pass |
| "3% per month" | "2% per month applies..." | fail/contradiction candidate |
| "within 30 days" | "within thirty (30) days" | pass with normalization |

Normalize formats where possible: `30 days` = `thirty (30) days`, `INR 5,000` = `5000 INR`, common date formats. Keep original quote verbatim in UI.

## 6) Contradiction detection (amendment-aware)

Contradictions are detected across evidence, not only within one claim.

### Detection heuristic
1. Identify question subject/field (late fee, eligibility age, interest rate, effective date, etc.).
2. Retrieve comparable chunks mentioning the subject across docs.
3. **Consult amendment graph first.** If the conflicting pair is explained by an `AMENDS`/`SUPERSEDES`/`REPLACES` edge, route it to Amendment Chains, not Contradiction Alerts.
4. Extract comparable values for unresolved pairs.
5. If same subject has incompatible values in different docs/sections, flag contradiction.

### Contradiction record

```json
{
  "contradiction_id": "x1",
  "subject": "late payment fee",
  "status": "contradicted",
  "conflict_type": "numeric",
  "values": [
    {
      "doc_name": "Contract_A.pdf",
      "page": 3,
      "chunk_id": "a_p3_c1",
      "sentence_id": "a_p3_c1#s0",
      "quote": "A late payment fee of 2% per month applies...",
      "normalized_value": "2% per month"
    },
    {
      "doc_name": "Contract_B.pdf",
      "page": 2,
      "chunk_id": "b_p2_c1",
      "sentence_id": "b_p2_c1#s0",
      "quote": "A late payment fee of 5% per month applies...",
      "normalized_value": "5% per month"
    }
  ],
  "explanation": "Both documents define late payment fee but specify different percentages."
}
```

## 7) Amendment chain resolution

### Detection
Look for cues in chunk text/metadata:
- "amends", "amendment to", "supersedes", "replaces", "revised", "effective from", "in lieu of"
- explicit dates and references to prior document names/versions

### Graph
```text
Doc A (2023) --amends--> Doc B (2024) --amends--> Doc C (2025)
```

Each edge stores: `from_doc`, `to_doc`, `effective_date`, `evidence_quote`, `evidence_chunk_id`, optional `evidence_sentence_id`.

### Resolution rule
- If question asks "which applies now/current/latest?", select node with latest effective date in the applicable chain.
- If dates missing/ambiguous, return chain and mark `status=ambiguous`; do not guess current rule.

## 8) Faithfulness scoring

```python
supported = count of verified shown answer sentences/claims
total = count of shown answer sentences/claims
faithfulness = 100.0 if total == 0 and abstained else round((supported / total) * 100, 1)
```

**Rules:**
- 1 claim = 1 atomic sentence, so claim-level and sentence-level faithfulness are identical.
- Compute over shown answer sentences/claims.
- Do not count blocked claims as supported.
- If abstaining fully, show `faithfulness_pct: null` or an explicit `N/A` label with reason; do not present 100% for an empty answer.
- Return both `faithfulness_pct` and `blocked_claims_count`.

Example response fields:
```json
{
  "faithfulness_pct": 100.0,
  "verified_sentences_count": 4,
  "total_shown_sentences": 4,
  "blocked_claims_count": 0
}
```

## 9) Abstention policy

Abstain when:
- No relevant evidence retrieved.
- All draft claims fail verification.
- Evidence is contradictory and no amendment/precedence rule resolves it.
- Question asks for information outside corpus.

Response shape:
```json
{
  "status": "abstained",
  "answer": "I don't have proof in the provided documents to answer this question.",
  "missing_evidence": [
    "No clause mentioning early closure penalty was found in indexed documents."
  ],
  "claims": [],
  "faithfulness_pct": null,
  "blocked_claims_count": 1
}
```

## 10) Logging for demo/debug

For every `/api/ask` call, store debug artifact:
- retrieved chunks + scores
- raw LLM draft
- source resolution decisions
- per-claim verification decisions
- contradiction/amendment outputs
- final answer and faithfulness

This makes it easy to explain failures to judges and to write tests from real cases.