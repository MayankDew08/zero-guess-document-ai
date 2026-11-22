from __future__ import annotations

import re
import uuid
from itertools import combinations

from app.amendments.graph import is_explained_by_amendment
from app.models.schemas import AmendmentEdge, Claim, Contradiction, ContradictionValue, RetrievalResult
from app.verification.nli import NLIProvider
from app.verification.numeric import extract_dates, extract_numbers


_SUBJECT_KEYWORDS = [
    "interest rate", "late fee", "late payment", "penalty", "tenure", "term",
    "eligibility", "coverage", "waiting period", "premium", "deductible",
    "notice period", "termination", "refund", "grace period",
]


def detect_contradictions(
    claims: list[Claim],
    retrieval: RetrievalResult,
    amendment_edges: list[AmendmentEdge],
    nli_provider: NLIProvider | None = None,
) -> list[Contradiction]:
    """Detect conflicts across supported/visible claims. Amendment-explained conflicts are excluded."""
    contradictions: list[Contradiction] = []
    seen_pairs: set[tuple[str, str]] = set()

    # Compare claims pairwise when they talk about similar subject and have conflicting values.
    for a, b in combinations(claims, 2):
        if a.status not in {"supported", "contradicted"} or b.status not in {"supported", "contradicted"}:
            continue
        pair_key = tuple(sorted([a.claim_id, b.claim_id]))
        if pair_key in seen_pairs:
            continue
        subject = _shared_subject(a.text, b.text)
        if not subject:
            continue
        # Skip if explained by amendment
        doc_a = a.citations[0].doc_id if a.citations else None
        doc_b = b.citations[0].doc_id if b.citations else None
        if doc_a and doc_b and is_explained_by_amendment(doc_a, doc_b, amendment_edges):
            continue

        conflict, conflict_type, severity, explanation = _is_conflict(a.text, b.text, nli_provider)
        if not conflict:
            continue
        seen_pairs.add(pair_key)
        contradictions.append(
            Contradiction(
                contradiction_id=f"ctr_{uuid.uuid4().hex[:8]}",
                subject=subject,
                conflict_type=conflict_type,
                severity=severity,
                status="confirmed" if severity in {"high", "medium"} else "possible",
                explanation=explanation,
                values=[
                    _claim_to_value(a),
                    _claim_to_value(b),
                ],
                affected_claim_ids=[a.claim_id, b.claim_id],
            )
        )

    # Also scan retrieved chunks for obvious numeric conflicts on same subject (even if LLM didn't draft both)
    contradictions.extend(_detect_from_retrieval(retrieval, amendment_edges, contradictions))

    return contradictions


def _shared_subject(a: str, b: str) -> str | None:
    la, lb = a.lower(), b.lower()
    for kw in _SUBJECT_KEYWORDS:
        if kw in la and kw in lb:
            return kw
    # fallback: token overlap on nouns/numbers context
    ta = set(re.findall(r"[a-z]{4,}", la))
    tb = set(re.findall(r"[a-z]{4,}", lb))
    overlap = ta & tb - {"that", "with", "from", "after", "before", "this", "shall", "will", "must", "applies"}
    if len(overlap) >= 2:
        return sorted(overlap)[0]
    return None


def _is_conflict(a: str, b: str, nli_provider: NLIProvider | None) -> tuple[bool, str, str, str]:
    a_nums, b_nums = set(extract_numbers(a)), set(extract_numbers(b))
    a_dates, b_dates = set(extract_dates(a)), set(extract_dates(b))

    if a_nums and b_nums and a_nums != b_nums:
        return True, "number", "high", f"Numeric values differ: {sorted(a_nums)} vs {sorted(b_nums)}."
    if a_dates and b_dates and a_dates != b_dates:
        return True, "date", "medium", f"Date values differ: {sorted(a_dates)} vs {sorted(b_dates)}."

    if nli_provider is not None:
        scores = nli_provider.predict(premise=a, hypothesis=b)
        if scores.get("contradiction", 0.0) >= 0.7:
            return True, "rule", "medium", f"NLI contradiction detected ({scores.get('contradiction', 0):.2f})."
    return False, "other", "low", ""


def _claim_to_value(c: Claim) -> ContradictionValue:
    cit = c.citations[0] if c.citations else None
    if cit:
        return ContradictionValue(
            doc_id=cit.doc_id,
            doc_name=cit.doc_name,
            page=cit.page,
            chunk_id=cit.chunk_id,
            sentence_id=cit.sentence_id,
            quote=cit.quote,
            bbox=cit.bbox,
            normalized_value=c.text,
        )
    return ContradictionValue(doc_id="", doc_name="", page=0, chunk_id="", quote=c.text, normalized_value=c.text)


def _detect_from_retrieval(
    retrieval: RetrievalResult,
    amendment_edges: list[AmendmentEdge],
    existing: list[Contradiction],
) -> list[Contradiction]:
    # Lightweight: look for same keyword with different numeric values in top retrieved chunks from different docs.
    out: list[Contradiction] = []
    existing_subjects = {c.subject.lower() for c in existing}
    chunks = [r.chunk for r in retrieval.chunks]
    for kw in _SUBJECT_KEYWORDS:
        matches = []
        for ch in chunks:
            for s in ch.sentences:
                if kw in s.text.lower():
                    nums = extract_numbers(s.text)
                    if nums:
                        matches.append((ch, s, nums))
        if len(matches) < 2:
            continue
        for (ch1, s1, n1), (ch2, s2, n2) in combinations(matches, 2):
            if ch1.doc_id == ch2.doc_id:
                continue
            if set(n1) == set(n2):
                continue
            if is_explained_by_amendment(ch1.doc_id, ch2.doc_id, amendment_edges):
                continue
            subj = kw
            if subj.lower() in existing_subjects:
                continue
            existing_subjects.add(subj.lower())
            out.append(
                Contradiction(
                    contradiction_id=f"ctr_{uuid.uuid4().hex[:8]}",
                    subject=subj,
                    conflict_type="number",
                    severity="high",
                    status="confirmed",
                    explanation=f"Different numeric values for '{subj}' across documents.",
                    values=[
                        ContradictionValue(doc_id=ch1.doc_id, doc_name=ch1.doc_name, page=ch1.page, chunk_id=ch1.chunk_id, sentence_id=s1.sentence_id, quote=s1.text, bbox=s1.bbox, normalized_value=",".join(n1)),
                        ContradictionValue(doc_id=ch2.doc_id, doc_name=ch2.doc_name, page=ch2.page, chunk_id=ch2.chunk_id, sentence_id=s2.sentence_id, quote=s2.text, bbox=s2.bbox, normalized_value=",".join(n2)),
                    ],
                )
            )
            break
    return out
