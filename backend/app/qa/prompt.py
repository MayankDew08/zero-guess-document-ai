from __future__ import annotations

import re

from app.models.schemas import RetrievedChunk

DEVANAGARI_RE = re.compile(r"[\u0900-\u097F]")


def is_hindi(text: str) -> bool:
    return bool(DEVANAGARI_RE.search(text or ""))


def build_claim_prompt(question: str, chunks: list[RetrievedChunk], doc_status: dict[str, str] | None = None,
                       hindi: bool | None = None) -> str:
    hindi = is_hindi(question) if hindi is None else hindi
    doc_status = doc_status or {}
    blocks = []
    for r in chunks:
        c = r.chunk
        head = f"### {c.doc_name} | page {c.page} | [Context: {c.section_context or c.section or '-'}] | document_status: {doc_status.get(c.doc_id, 'STANDALONE')}"
        if c.chunk_type == "table":
            head += f" | table columns: {c.metadata.get('table_header')}"
        lines = [f"[{s.sentence_id}] {s.text}" for s in c.sentences]
        blocks.append(head + "\n" + "\n".join(lines))
    evidence_json = "\n\n".join(blocks)
    if hindi:
        language_rule = ("- The question is in Hindi. Write the text of EVERY claim in natural Hindi (Devanagari script), "
                         "but keep all numbers, percentages, currency amounts (e.g. 2%, INR 1,000, Rs 50,000), durations and dates "
                         "EXACTLY as written in the English evidence using ASCII digits (never Devanagari digits), and keep source_ids "
                         "exactly as in the evidence. Translate the cited English sentence faithfully into Hindi: do NOT add words that are not in that sentence (for example 'according to the latest rule' or 'as per the policy'). Never start a claim with phrases from the question such as 'नवीनतम सक्रिय नियम के अनुसार'. Example: evidence sentence 'The processing fee is INR 500 at disbursement.' -> claim text 'प्रोसेसिंग शुल्क वितरण के समय INR 500 है।'. Write missing_evidence entries in Hindi too.\n")
    else:
        language_rule = "- The question may be in any language; write claims in English.\n"
    return f"""You are a strict evidence extraction assistant. Answer using ONLY the provided evidence.

RULES:
- Output VALID JSON only. No markdown, no commentary.
{language_rule}- Create atomic factual claims: 1 claim = 1 sentence, restating exactly what ONE cited sentence says.
- A claim must say only what its cited sentence says: do not add qualifiers, dates, document names or reasoning that are not in that sentence.
- Reuse the cited sentence's own words, including its nouns: do NOT swap in synonyms from the question (if the sentence says 'Applicants', write 'Applicants', not 'Borrowers').
- Keep every number, percentage, currency amount, duration and date EXACTLY as written in the cited sentence.
- Each claim MUST cite 1-2 source_ids copied character-for-character from the square brackets in front of an evidence sentence (e.g. [doc_p1_c1#s0] -> "doc_p1_c1#s0"). Cite the sentence you restate, nothing else. Never invent ids or quotes.
- Each evidence group header shows [Context: ...]: the document topic and section the sentences belong to. Use sentences only from the group whose context matches what the question asks about (e.g. a question about AIML-02 must not use sentences under an AIML-01 context). Identical section names under different topics are different sections.
- If the question names a section (e.g. 'bonus features', 'deliverables', 'must-have features'), answer ONLY from sentences whose [Context] ends with that section name and include every sentence of that section that is relevant.
- Table rows list their cells separated by " | " in the order of the table columns: name the fee type and its amount in the claim.
- document_status tells you which rules are live: ACTIVE = latest in an amendment chain, SUPERSEDED = replaced by a newer document (historical only), STANDALONE = no amendment link.
- For "latest / current / active" questions you MUST include a claim from the ACTIVE document that answers the question; never present a SUPERSEDED document's value as the current rule.
- If STANDALONE and ACTIVE documents disagree, state each one as its own claim (one per document); never resolve the disagreement yourself.
- Never do arithmetic and never copy amounts or periods from the question into a claim. For calculation questions only state the applicable rate/rule found in the evidence (cite the sentence containing the rate); a separate deterministic calculator computes the result.
- If the question has several parts, answer each part the evidence supports and list every part with no supporting evidence in missing_evidence (e.g. "No evidence found for <part>"). Never invent a value for an unsupported part.
- Only fill missing_evidence when some part of the question has no supporting evidence; if every part is answered, return "missing_evidence": [].
- If the evidence does not answer the question, return "claims": [] and explain what is missing in missing_evidence. Do not guess.

OUTPUT SCHEMA:
{{"claims":[{{"claim_id":"c1","text":"one atomic claim sentence","claim_type":"factual|numeric|date|rule|definition|other","source_ids":["chunk_id#s0"]}}],"missing_evidence":["..."]}}

QUESTION:
{question}

EVIDENCE:
{evidence_json}
"""
