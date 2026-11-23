from __future__ import annotations

from app.models.schemas import Claim


def compute_faithfulness(shown: list[Claim], blocked: list[Claim] | None = None) -> dict:
    """1 claim = 1 atomic sentence.

    * faithfulness_pct: % of sentences *shown to the user* backed by >=1 verified source quote
      (blocked claims are never shown, so this is 100% unless something slips through).
    * draft_support_pct: % of everything the LLM drafted that survived verification - the honest
      measure of how much the generator needed the verifier.
    """
    blocked = blocked or []
    total = len(shown)
    verified = sum(1 for c in shown if c.status == "supported" and c.citations)
    drafted = total + len(blocked)
    return {
        "faithfulness_pct": round(verified / total * 100, 1) if total else None,
        "verified_sentences_count": verified,
        "total_shown_sentences": total,
        "blocked_claims_count": len(blocked),
        "drafted_claims_count": drafted,
        "draft_support_pct": round(verified / drafted * 100, 1) if drafted else None,
    }
