from __future__ import annotations

import json

from app.models.schemas import RetrievedChunk


def build_claim_prompt(question: str, chunks: list[RetrievedChunk]) -> str:
    evidence = []
    for r in chunks:
        c = r.chunk
        evidence.append(
            {
                "chunk_id": c.chunk_id,
                "doc_name": c.doc_name,
                "page": c.page,
                "sentences": [{"sentence_id": s.sentence_id, "text": s.text} for s in c.sentences],
            }
        )
    evidence_json = json.dumps(evidence, ensure_ascii=False, indent=2)
    return f"""You are a strict evidence extraction assistant. Answer using ONLY the provided evidence.

RULES:
- Output VALID JSON only. No markdown, no commentary.
- Create atomic factual claims (1 claim = 1 sentence).
- Each claim MUST cite source_ids using the provided sentence_id values (e.g. "doc_p1_c1#s0").
- Do NOT invent quotes. Do NOT cite anything not in evidence.
- If evidence is missing or insufficient, add a clear message to missing_evidence and do not guess.
- Do not resolve contradictions by guessing; state what is supported.

OUTPUT SCHEMA:
{{
  "claims": [
    {{
      "claim_id": "c1",
      "text": "atomic claim sentence",
      "claim_type": "factual|numeric|date|rule|definition|other",
      "source_ids": ["chunk_id#s0"]
    }}
  ],
  "missing_evidence": ["..."]
}}

QUESTION:
{question}

EVIDENCE:
{evidence_json}
"""
