from __future__ import annotations

import re
from datetime import datetime

# Numbers incl. Indian grouping (1,00,000) and optional lakh/crore multiplier; optional currency prefix.
NUMBER_PATTERN = r"\d+(?:,\d{2,3})*(?:\.\d+)?"
_MULT = {"lakh": 100_000, "lakhs": 100_000, "lac": 100_000, "lacs": 100_000,
         "crore": 10_000_000, "crores": 10_000_000, "cr": 10_000_000}
_NUM_RE = re.compile(
    r"(?<!\w)(?P<cur>₹|rs\.?|inr|\$|€|£)?\s*(?P<num>" + NUMBER_PATTERN + r")\s*(?P<mult>lakhs?|lacs?|crores?|cr\b)?\s*(?P<pct>%)?",
    re.IGNORECASE,
)
_DATE_RE = re.compile(
    r"\b(?:\d{1,2}[/.-]\d{1,2}[/.-]\d{2,4}|\d{4}[/-]\d{1,2}[/-]\d{1,2}|"
    r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?\s+\d{1,2},?\s+\d{4}|"
    r"\d{1,2}\s+(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?\s+\d{4})\b",
    re.IGNORECASE,
)


# Identifier codes are labels, not quantities: AIML-02, CS-01, W3-01, v3, RBI/2023-24/28, Section 4.2, Page 6, p.5
_KEYWORD_REF_RE = re.compile(
    r"\b(?:section|sec|clause|article|annexure|annex|appendix|schedule|chapter|para|paragraph|page|pg|pp?|rule|regulation|"
    r"item|step|point|figure|fig|table|no|ref|serial)\b\.?\s*\.?\s*\d+(?:[.\-/]\d+)*(?:\([a-z0-9]+\))?",
    re.IGNORECASE,
)
_TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9/_.\-]*[A-Za-z0-9]|[A-Za-z0-9]")
_QUANTITY_TOKEN_RE = re.compile(
    r"^(?:(?:₹|rs\.?|inr|usd|eur|gbp)\d[\d,.]*|\d[\d,.]*-?(?:days?|weeks?|months?|years?|lakhs?|lacs?|crores?|cr|%|st|nd|rd|th))$",
    re.IGNORECASE,
)
# strict, uppercase-led codes that must be attributed to the right context (AIML-02, CS-01, RBI/2023-24/28)
_STRICT_CODE_RE = re.compile(r"\b[A-Z][A-Z0-9]{1,}[-/][A-Z0-9][A-Z0-9/\-.]*\d[A-Z0-9/\-.]*\b|\b[A-Z]{2,}[-/]\d[\dA-Z/\-.]*\b")


def mask_identifiers(text: str) -> str:
    """Blank out identifier codes so their digits are not mistaken for quantities."""
    text = text or ""
    chars = list(text)

    def blank(a: int, b: int) -> None:
        for i in range(a, b):
            chars[i] = " "

    for m in _KEYWORD_REF_RE.finditer(text):
        blank(*m.span())
    for m in _TOKEN_RE.finditer(text):
        tok = m.group(0).rstrip(".")
        if any(c.isalpha() for c in tok) and any(c.isdigit() for c in tok) and not _QUANTITY_TOKEN_RE.match(tok):
            blank(*m.span())
    return "".join(chars)


def extract_identifier_codes(text: str) -> set[str]:
    return {re.sub(r"[\s.]+$", "", m.group(0)).upper() for m in _STRICT_CODE_RE.finditer(text or "")}


def extract_numbers(text: str) -> list[str]:
    vals = []
    for m in _NUM_RE.finditer(mask_identifiers(text)):
        norm = _normalize_parts(m.group("cur"), m.group("num"), m.group("mult"), m.group("pct"))
        if norm:
            vals.append(norm)
    return vals


def parse_amount_value(num: str, mult: str | None = None) -> float:
    """'1,00,000' -> 100000.0 ; ('5', 'lakh') -> 500000.0"""
    v = float(num.replace(",", ""))
    return v * _MULT[mult.lower()] if mult else v


def _normalize_parts(cur: str | None, num: str, mult: str | None, pct: str | None) -> str | None:
    cur_n = {"₹": "inr", "rs": "inr", "rs.": "inr", "inr": "inr", "$": "usd", "€": "eur", "£": "gbp"}.get((cur or "").lower(), "")
    try:
        value = parse_amount_value(num, mult)
    except ValueError:
        return None
    text = f"{value:.6f}".rstrip("0").rstrip(".")
    return f"{cur_n}{text}{'%' if pct else ''}"


def extract_dates(text: str) -> list[str]:
    vals = []
    for m in _DATE_RE.finditer(mask_identifiers(text)):
        norm = _normalize_date(m.group(0))
        if norm:
            vals.append(norm)
    return vals


def _normalize_date(raw: str) -> str | None:
    raw = raw.strip().replace(",", "")
    fmts = [
        "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y", "%m/%d/%Y", "%m-%d-%Y",
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


def check_numeric_date_match(claim: str, quote: str, context: str = "") -> tuple[bool, str | None]:
    """Return (ok, reason_if_failed). Every quantity/date in the claim must appear in the quote; identifier codes
    (AIML-02, CS-01, ...) are not quantities but must be attributable to quote + section context."""
    claim_nums = extract_numbers(claim)
    quote_nums = set(extract_numbers(quote))
    claim_dates = extract_dates(claim)
    quote_dates = set(extract_dates(quote))

    missing_codes = sorted(extract_identifier_codes(claim) - extract_identifier_codes(f"{context} {quote}"))
    missing_nums = [n for n in claim_nums if n not in quote_nums]
    missing_dates = [d for d in claim_dates if d not in quote_dates]

    # Allow some tolerance: if claim has no numeric/date tokens, pass this check.
    if not claim_nums and not claim_dates and not missing_codes:
        return True, None

    if missing_nums or missing_dates or missing_codes:
        parts = []
        if missing_codes:
            parts.append(f"identifier not in quote/section context: {missing_codes}")
        if missing_nums:
            parts.append(f"numbers not in quote: {missing_nums}")
        if missing_dates:
            parts.append(f"dates not in quote: {missing_dates}")
        return False, "; ".join(parts)
    return True, None
