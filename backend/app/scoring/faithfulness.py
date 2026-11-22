from __future__ import annotations

from app.models.schemas import Claim


def compute_faithfulness(claims: list[Claim]) -> dict:
    # 1 claim = 1 atomic sentence/answer unit shown to user.
    shown = [c for c in claims if c.status in {"supported", "unsupported", "contradicted", "abstained"} and c.status != "blocked"]
    # For our API, supported claims are shown; unsupported/contradicted shown as flagged; blocked not shown.
    shown = [c for c in claims if c.status != "blocked"]
    total = len(shown)
    verified = sum(1 for c in shown if c.status == "supported")
    pct = round((verified / total) * 100, 1) if total > 0 else None
    return {
        "faithfulness_pct": pct,
        "verified_sentences_count": verified,
        "total_shown_sentences": total,
    }
