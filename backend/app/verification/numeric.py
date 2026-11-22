from __future__ import annotations

import re
from datetime import datetime

_NUM_RE = re.compile(r"(?<!\w)(?:₹|rs\.?|inr|\$|€|£)?\s*\d+(?:,\d{3})*(?:\.\d+)?\s*%?", re.IGNORECASE)
_DATE_RE = re.compile(
    r"\b(?:\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\d{4}[/-]\d{1,2}[/-]\d{1,2}|"
    r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?\s+\d{1,2},?\s+\d{4}|"
    r"\d{1,2}\s+(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?\s+\d{4})\b",
    re.IGNORECASE,
)


def extract_numbers(text: str) -> list[str]:
    vals = []
    for m in _NUM_RE.finditer(text or ""):
        raw = m.group(0).strip()
        norm = _normalize_number(raw)
        if norm:
            vals.append(norm)
    return vals


def extract_dates(text: str) -> list[str]:
    vals = []
    for m in _DATE_RE.finditer(text or ""):
        norm = _normalize_date(m.group(0))
        if norm:
            vals.append(norm)
    return vals


def _normalize_number(raw: str) -> str | None:
    s = raw.lower().replace(",", "").replace(" ", "")
    s = s.replace("rs.", "inr").replace("rs", "inr").replace("₹", "inr")
    s = s.replace("$", "usd").replace("€", "eur").replace("£", "gbp")
    # keep only meaningful numeric tokens (ignore bare years? no, keep them; but be careful)
    m = re.fullmatch(r"(inr|usd|eur|gbp)?(\d+(?:\.\d+)?)(%)?", s)
    if not m:
        return None
        # skip very short bare numbers that are likely not claim-critical? keep them.
    cur, num, pct = m.group(1) or "", m.group(2), m.group(3) or ""
    # normalize 2.0 -> 2
    if "." in num:
        num = num.rstrip("0").rstrip(".")
    return f"{cur}{num}{pct}"


def _normalize_date(raw: str) -> str | None:
    raw = raw.strip().replace(",", "")
    fmts = [
        "%d/%m/%Y", "%d-%m-%Y", "%m/%d/%Y", "%m-%d-%Y",
        "%Y-%m-%d", "%Y/%m/%d", "%d/%m/%y", "%d-%m-%y",
        "%b %d %Y", "%B %d %Y", "%d %b %Y", "%d %B %Y",
        "%b. %d %Y", "%d %b. %Y",
    ]
    for fmt in fmts:
        try:
            dt = datetime.strptime(raw, fmt)
            return dt.strftime("%Y-%m-%d")
        except Exception:
            pass
    # try with comma removed already; also try original with comma
    return raw.lower()


def check_numeric_date_match(claim: str, quote: str) -> tuple[bool, str | None]:
    """Return (ok, reason_if_failed). Every numeric/date token in claim must be matched in quote."""
    claim_nums = extract_numbers(claim)
    quote_nums = set(extract_numbers(quote))
    claim_dates = extract_dates(claim)
    quote_dates = set(extract_dates(quote))

    missing_nums = [n for n in claim_nums if n not in quote_nums]
    missing_dates = [d for d in claim_dates if d not in quote_dates]

    # Allow some tolerance: if claim has no numeric/date tokens, pass this check.
    if not claim_nums and not claim_dates:
        return True, None

    if missing_nums or missing_dates:
        parts = []
        if missing_nums:
            parts.append(f"numbers not in quote: {missing_nums}")
        if missing_dates:
            parts.append(f"dates not in quote: {missing_dates}")
        return False, "; ".join(parts)
    return True, None
