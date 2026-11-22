from __future__ import annotations

import uuid
from typing import Any

from app.core.config import settings
from app.core.store import AppStore
from app.models.schemas import (
    Citation,
    Claim,
    DraftClaim,
    RetrievalResult,
)
from app.verification.nli import NLIProvider
from app.verification.numeric import check_numeric_date_match


def resolve_and_verify_claims(
    draft_claims: list[DraftClaim],
    store: AppStore,
    nli_provider: NLIProvider,
) -> tuple[list[Claim], list[Claim]]:
    """Gate 2 + Gate 3. Returns (shown_claims, blocked_claims)."""
    shown: list[Claim] = []
    blocked: list[Claim] = []

    for draft in draft_claims:
        claim = Claim(
            claim_id=draft.claim_id or f"clm_{uuid.uuid4().hex[:8]}",
            text=draft.text.strip(),
            claim_type=draft.claim_type,
            status="unsupported",
            source_ids=list(draft.source_ids),
            citations=[],
        )

        if not claim.text:
            claim.status = "blocked"
            claim.reason = "empty_claim_text"
            blocked.append(claim)
            continue

        if not draft.source_ids:
            claim.status = "blocked"
            claim.reason = "no_source_ids"
            blocked.append(claim)
            continue

        # Gate 2: resolve source IDs
        citations: list[Citation] = []
        resolve_failed = False
        for sid in draft.source_ids:
            s = store.get_sentence(sid)
            if not s:
                claim.status = "blocked"
                claim.reason = f"unresolved_source_id:{sid}"
                blocked.append(claim)
                resolve_failed = True
                break
            bbox = None
            if s.get("bbox"):
                b = s["bbox"]
                bbox = {
                    "x0": b["x0"], "y0": b["y0"], "x1": b["x1"], "y1": b["y1"],
                    "page_width": b.get("page_width", 612), "page_height": b.get("page_height", 792),
                }
            citations.append(
                Citation(
                    sentence_id=s["sentence_id"],
                    chunk_id=s["chunk_id"],
                    doc_id=s["doc_id"],
                    doc_name=s["doc_name"],
                    page=s["page"],
                    quote=s["text"],
                    bbox=bbox,
                    verification_status="verified",
                    support_status="unchecked",
                )
            )
        if resolve_failed:
            continue

        claim.citations = citations
        merged_quote = " ".join(c.quote for c in citations).strip()

        # Gate 3a: NLI
        nli_scores = nli_provider.predict(premise=merged_quote, hypothesis=claim.text)
        nli_label = max(nli_scores, key=nli_scores.get) if nli_scores else "neutral"
        for c in claim.citations:
            c.nli_label = nli_label
            c.nli_scores = nli_scores

        entail_ok = nli_label == "entailment" and nli_scores.get("entailment", 0.0) >= settings.nli_entailment_threshold
        contradicted = nli_label == "contradiction" and nli_scores.get("contradiction", 0.0) >= settings.nli_contradiction_threshold

        # Gate 3b: numeric/date
        num_ok, num_reason = check_numeric_date_match(claim.text, merged_quote)

        notes = [f"nli={nli_label}", f"numeric_match={num_ok}"]
        if num_reason:
            notes.append(num_reason)

        if contradicted:
            claim.status = "contradicted"
            claim.reason = f"nli_contradiction:{nli_scores.get('contradiction', 0):.3f}"
            for c in claim.citations:
                c.support_status = "contradicted"
                c.verification_notes = ";".join(notes)
            shown.append(claim)
            continue

        if entail_ok and num_ok:
            claim.status = "supported"
            claim.reason = None
            for c in claim.citations:
                c.support_status = "supported"
                c.verification_notes = ";".join(notes)
            shown.append(claim)
        else:
            claim.status = "blocked"
            reasons = []
            if not entail_ok:
                reasons.append(f"nli_not_entailed:{nli_label}:{nli_scores.get(nli_label, 0):.3f}")
            if not num_ok:
                reasons.append(num_reason or "numeric_date_mismatch")
            claim.reason = "; ".join(reasons)
            for c in claim.citations:
                c.support_status = "not_enough_info"
                c.verification_notes = ";".join(notes)
            blocked.append(claim)

    return shown, blocked
