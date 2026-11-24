from __future__ import annotations

import re
import uuid

from app.core.config import settings
from app.core.store import AppStore
from app.models.schemas import (
    Citation,
    Claim,
    DraftClaim,
)
from app.verification.nli import NLIProvider
from app.verification.numeric import check_numeric_date_match

_SID_FIX_RE = re.compile(r"^(?P<c>.+?)[#_ ]s?(?P<n>\d+)$")
_LIST_MARKER_RE = re.compile(r"^\s*(?:\([A-Za-z0-9]{1,3}\)|[A-Za-z0-9]{1,3}[.)])\s+")
_NEGATION_RE = re.compile(r"\b(?:not|no|never|cannot|can't|doesn't|don't|isn't|aren't|won't|cannot|must\s+not|shall\s+not)\b", re.I)


def _tokens(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", (text or "").lower()))


def _verbatim_restatement(claim_text: str, quote: str) -> str | None:
    """A near-copy claim that the NLI model rejected only because of a synonym (e.g. Borrowers vs Applicants)
    can be re-grounded to the cited sentence itself. Returns the cleaned quote, or None when the claim carries
    extra/negated content and must stay blocked."""
    clean = _LIST_MARKER_RE.sub("", quote or "").strip()
    if not clean or len(clean) > 400:
        return None
    claim_tokens = _tokens(claim_text)
    quote_tokens = _tokens(clean)
    if len(claim_tokens) < 4 or not quote_tokens:
        return None
    if _NEGATION_RE.search(claim_text or "") and not _NEGATION_RE.search(clean):
        return None
    if len(claim_tokens & quote_tokens) / len(claim_tokens) < 0.85:
        return None
    return clean


def _entails(scores: dict[str, float]) -> bool:
    return bool(scores) and max(scores, key=scores.get) == "entailment" and scores.get("entailment", 0.0) >= settings.nli_entailment_threshold


def repair_source_id(sid: str, store: AppStore) -> str:
    """Format-only repair of an LLM-written sentence id (e.g. 'chunk#1' -> 'chunk#s1').
    Never invents evidence: the repaired id must exist in the store, otherwise it stays invalid."""
    s = (sid or "").strip().strip("\"'[]() ")
    if store.get_sentence(s):
        return s
    m = _SID_FIX_RE.match(s)
    if m:
        cand = f"{m.group('c')}#s{m.group('n')}"
        if store.get_sentence(cand):
            return cand
    return sid


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

        claim.source_ids = [repair_source_id(x, store) for x in draft.source_ids]
        draft = draft.model_copy(update={"source_ids": claim.source_ids})
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
                    section_context=s.get("section_context") or None,
                    bbox=bbox,
                    verification_status="verified",
                    support_status="unchecked",
                )
            )
        if resolve_failed:
            continue

        claim.citations = citations
        merged_quote = " ".join(c.quote for c in citations).strip()
        contexts = list(dict.fromkeys(c.section_context for c in citations if c.section_context))
        context = " | ".join(contexts)
        # NLI sees "topic > section: quote" so a bullet is judged within the section it belongs to;
        # citations/reports still show only the pure verbatim quote.
        premise = f"{context}: {merged_quote}" if context else merged_quote

        # Gate 3a: NLI (true 3-class entailment/neutral/contradiction)
        if nli_provider is None:
            nli_scores, nli_label = {}, "skipped"
            entail_ok, contradicted = True, False
        else:
            # Contextual premise first (helps bullets/sub-clauses); the plain quote is the fallback so a long
            # heading prefix can never turn a clean sentence into a false "contradiction".
            nli_scores = nli_provider.predict(premise=premise, hypothesis=claim.text)
            if context and not _entails(nli_scores):
                nli_scores = nli_provider.predict(premise=merged_quote, hypothesis=claim.text)  # legacy plain-quote verdict
            nli_label = max(nli_scores, key=nli_scores.get) if nli_scores else "neutral"
            entail_ok = _entails(nli_scores)
            contradicted = nli_label == "contradiction" and nli_scores.get("contradiction", 0.0) >= settings.nli_contradiction_threshold
        for c in claim.citations:
            c.nli_label = nli_label
            c.nli_scores = nli_scores

        # Gate 3b: deterministic numeric/date check
        num_ok, num_reason = check_numeric_date_match(claim.text, merged_quote, context)
        claim.numeric_verification = {
            "ok": bool(num_ok),
            "reason": num_reason,
            "claim_numbers": re.findall(r"\d+(?:[\.,]\d+)?%?", claim.text),
            "evidence_numbers": re.findall(r"\d+(?:[\.,]\d+)?%?", merged_quote),
        }
        notes = [f"nli={nli_label}", f"numeric_match={num_ok}"]
        if num_reason:
            notes.append(num_reason)

        # NLI can call a synonym-only paraphrase ("Borrowers" vs "Applicants") a contradiction. If the claim is
        # otherwise a near-copy of the quote, re-ground it to the stored sentence and verify that exact sentence.
        if not entail_ok and num_ok and nli_provider is not None:
            restated = _verbatim_restatement(claim.text, merged_quote)
            if restated and restated != claim.text:
                restated_scores = nli_provider.predict(premise=merged_quote, hypothesis=restated)
                if _entails(restated_scores):
                    claim.text = restated
                    nli_scores, nli_label = restated_scores, max(restated_scores, key=restated_scores.get)
                    entail_ok, contradicted = True, False
                    notes = [f"nli={nli_label}", "numeric_match=True", "restated_from_cited_quote"]
                    for c in claim.citations:
                        c.nli_label, c.nli_scores = nli_label, nli_scores

        if entail_ok and num_ok:
            claim.status = "supported"
            claim.reason = None
            for c in claim.citations:
                c.support_status = "supported"
                c.verification_notes = ";".join(notes)
            shown.append(claim)
            continue

        # Unsupported / neutral / contradicted claims are BLOCKED: never shown as answer.
        reasons = []
        if contradicted:
            reasons.append(f"contradicted_by_cited_evidence (nli_contradiction={nli_scores.get('contradiction', 0):.2f})")
        elif not entail_ok:
            reasons.append(f"unsupported_by_cited_evidence (nli={nli_label}:{nli_scores.get(nli_label, 0):.2f})")
        if not num_ok:
            reasons.append(f"numeric_date_mismatch ({num_reason})")
        claim.status = "blocked"
        claim.reason = "; ".join(reasons)
        for c in claim.citations:
            c.support_status = "contradicted" if contradicted else "not_enough_info"
            c.verification_notes = ";".join(notes)
        blocked.append(claim)

    return shown, blocked
