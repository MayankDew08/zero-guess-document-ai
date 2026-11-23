from __future__ import annotations

from app.models.schemas import RetrievedChunk


def build_claim_prompt(question: str, chunks: list[RetrievedChunk], doc_status: dict[str, str] | None = None) -> str:
    doc_status = doc_status or {}
    blocks = []
    for r in chunks:
        c = r.chunk
        head = f"### {c.doc_name} | page {c.page} | section: {c.section or '-'} | document_status: {doc_status.get(c.doc_id, 'STANDALONE')}"
        if c.chunk_type == "table":
            head += f" | table columns: {c.metadata.get('table_header')}"
        lines = [f"[{s.sentence_id}] {s.text}" for s in c.sentences]
        blocks.append(head + "\n" + "\n".join(lines))
    evidence_json = "\n\n".join(blocks)
    return f"""You are a strict evidence extraction assistant. Answer using ONLY the provided evidence.

RULES:
- Output VALID JSON only. No markdown, no commentary.
- The question may be in any language (e.g. Hindi); always write claims in English.
- Create atomic factual claims: 1 claim = 1 sentence, restating exactly what ONE cited sentence says.
- Keep every number, percentage, currency amount, duration and date EXACTLY as written in the cited sentence.
- Each claim MUST cite 1-2 source_ids copied character-for-character from the square brackets in front of an evidence sentence (e.g. [doc_p1_c1#s0] -> "doc_p1_c1#s0"). Cite the sentence you restate, nothing else. Never invent ids or quotes.
- Table rows list their cells separated by " | " in the order of the table columns: name the fee type and its amount in the claim.
- document_status tells you which rules are live: ACTIVE = latest in an amendment chain, SUPERSEDED = replaced by a newer document (historical only), STANDALONE = no amendment link.
- For "latest / current / active" questions use ACTIVE or STANDALONE documents and do not present a SUPERSEDED document's value as the current rule.
- If STANDALONE and ACTIVE documents disagree, state each one as its own claim (one per document); never resolve the disagreement yourself.
- Never do arithmetic and never copy amounts or periods from the question into a claim. For calculation questions only state the applicable rate/rule found in the evidence (cite the sentence containing the rate); a separate deterministic calculator computes the result.
- If the evidence does not answer the question, return "claims": [] and explain what is missing in missing_evidence. Do not guess.

OUTPUT SCHEMA:
{{"claims":[{{"claim_id":"c1","text":"one atomic claim sentence","claim_type":"factual|numeric|date|rule|definition|other","source_ids":["chunk_id#s0"]}}],"missing_evidence":["..."]}}

QUESTION:
{question}

EVIDENCE:
{evidence_json}
"""
