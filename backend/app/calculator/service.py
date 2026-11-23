"""Deterministic clause calculator.

The rate comes from a verified, stored sentence of the *active* rule (never from the LLM) and all
arithmetic is plain Decimal math. Supports late-payment penalty/fee, simple interest and EMI.
"""
from __future__ import annotations

import re
from decimal import ROUND_HALF_UP, Decimal, getcontext

from app.amendments.graph import active_chain_doc_ids
from app.contradictions.detector import looks_like_heading, subjects_in, typed_values
from app.core.store import AppStore
from app.models.schemas import Calculation, Citation, Contradiction

getcontext().prec = 28

_AMOUNT_RE = re.compile(r"(?:₹|\brs\.?|\binr|\brupees?)\s*([\d,]+(?:\.\d+)?)|([\d,]+(?:\.\d+)?)\s*(?:rupees|inr)\b", re.I)
_PERIOD_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(day|week|month|year)s?\b", re.I)
_CALC_WORDS = re.compile(r"\b(calculate|compute|work\s+out|how\s+much|total)\b|गणना|कितना", re.I)
_TOPIC_WORDS = re.compile(r"\b(fee|penalty|charge|interest|emi|instal?ment)\b|शुल्क|ब्याज", re.I)


def is_calculation_query(question: str) -> bool:
    return bool(_CALC_WORDS.search(question) and _TOPIC_WORDS.search(question) and _AMOUNT_RE.search(question))


def _money(v: Decimal) -> str:
    v = v.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return f"Rs {v:,.0f}" if v == v.to_integral_value() else f"Rs {v:,.2f}"


def _num(v: Decimal) -> str:
    return f"{v.normalize():f}" if v != v.to_integral_value() else f"{int(v)}"


def parse_amount(question: str) -> Decimal | None:
    m = _AMOUNT_RE.search(question)
    if not m:
        return None
    return Decimal((m.group(1) or m.group(2)).replace(",", ""))


def parse_months(question: str) -> Decimal | None:
    m = _PERIOD_RE.search(question)
    if not m:
        return None
    n, unit = Decimal(m.group(1)), m.group(2).lower()
    return {"month": n, "year": n * 12, "week": n * 12 / 52, "day": n / 30}[unit]


def _kind(question: str) -> str:
    q = question.lower()
    if re.search(r"\blate\b|penalt|overdue|\bdelay|विलंब", q):
        return "late_fee"
    if re.search(r"\bemi\b|instal?ment", q):
        return "emi"
    return "interest"


def _candidate_docs(app_store: AppStore) -> set[str]:
    heads = active_chain_doc_ids(app_store.amendment_edges)
    return heads or set(app_store.documents)


def find_rate(app_store: AppStore, subject: str, doc_ids: set[str]):
    """First verified prose sentence of an active doc stating a % for `subject`."""
    best = None
    for ch in app_store.all_chunks():
        if ch.doc_id not in doc_ids:
            continue
        for s in ch.sentences:
            if looks_like_heading(s.text) or subject not in subjects_in(s.text):
                continue
            pct = [v for v in typed_values(s.text) if v[0] == "percent"]
            if not pct:
                continue
            rank = 1 if ch.chunk_type == "table" else 0
            if best is None or rank < best[0]:
                best = (rank, s, pct[0], ch)
    if not best:
        return None
    _, sent, (_, value, raw), ch = best
    low = sent.text.lower()
    period = "month" if re.search(r"per\s+month|monthly|a\s+month", low) else (
        "year" if re.search(r"per\s+(?:year|annum)|p\.a\.|annual|yearly|a\s+year", low) else None)
    return sent, Decimal(str(value)), period, ch


def _citation(app_store: AppStore, sentence_id: str) -> Citation | None:
    s = app_store.get_sentence(sentence_id)
    if not s:
        return None
    return Citation(sentence_id=s["sentence_id"], chunk_id=s["chunk_id"], doc_id=s["doc_id"], doc_name=s["doc_name"],
                    page=s["page"], quote=s["text"], bbox=s.get("bbox"), verification_status="verified",
                    support_status="supported")


def calculate(question: str, app_store: AppStore,
              contradictions: list[Contradiction] | None = None) -> tuple[Calculation | None, list[str]]:
    """Return (calculation, missing_inputs). `calculation` is None if it cannot be computed."""
    amount = parse_amount(question)
    months = parse_months(question)
    kind = _kind(question)
    missing: list[str] = []
    if amount is None:
        missing.append("An amount (e.g. 'Rs 50,000') is needed to calculate.")
        return None, missing
    docs = _candidate_docs(app_store)
    subject = "late payment fee" if kind == "late_fee" else "interest rate"
    found = find_rate(app_store, subject, docs)
    if not found:
        missing.append(f"No verified '{subject}' percentage found in the active documents.")
        return None, missing
    sent, rate, period, ch = found
    cit = _citation(app_store, sent.sentence_id)
    src = f"{ch.doc_name} p.{ch.page}"
    warnings = [
        f"Conflicting value in {v.doc_name} p.{v.page}: “{v.quote}” — unresolved; result uses the active policy rule."
        for c in (contradictions or []) if c.subject == subject for v in c.values if v.doc_id != ch.doc_id
    ]

    if kind == "late_fee":
        if months is None:
            missing.append("An overdue period (e.g. '2 months') is needed.")
            return None, missing
        if period == "year":
            periods, unit, label = months / 12, "year", "annual"
        else:
            periods, unit, label = months, "month", "monthly"
        per_period = (amount * rate / 100)
        total = per_period * periods
        steps = [
            f"Active rule rate: {_num(rate)}% per {unit} ({src}).",
            f"Overdue amount = {_money(amount)}; overdue period = {_num(months)} month(s).",
            f"Fee per {unit} = {_money(amount)} × {_num(rate)}% = {_money(per_period)}.",
            f"Total late fee = {_money(per_period)} × {_num(periods)} {unit}(s) = {_money(total)}.",
        ]
        return Calculation(
            kind="late_payment_fee",
            formula=f"late_fee = overdue_amount × {label}_rate% × number_of_{unit}s (simple, non-compounding)",
            inputs={"overdue_amount": float(amount), "rate_percent": float(rate), "rate_period": unit,
                    "periods": float(periods), "source": src},
            steps=steps, result=_money(total), result_value=float(total.quantize(Decimal("0.01"))),
            citation=cit, warnings=warnings), missing

    # interest / EMI need a tenure
    if months is None:
        tenure = find_rate_tenure(app_store, docs)
        months = tenure
    if months is None:
        missing.append("A tenure/period (e.g. '24 months') is needed.")
        return None, missing
    if kind == "emi":
        r = rate / 12 / 100
        growth = (1 + r) ** int(months)
        emi = amount * r * growth / (growth - 1)
        steps = [
            f"Active rule rate: {_num(rate)}% per year ({src}); monthly rate r = {_num(rate)}% ÷ 12 = {r * 100:.4f}%.",
            f"Principal = {_money(amount)}; tenure n = {_num(months)} months.",
            f"EMI = P × r × (1+r)^n ÷ ((1+r)^n − 1) = {_money(emi)}.",
        ]
        return Calculation(
            kind="emi", formula="EMI = P × r × (1+r)^n / ((1+r)^n − 1), r = annual_rate / 12 / 100",
            inputs={"principal": float(amount), "annual_rate_percent": float(rate), "months": float(months), "source": src},
            steps=steps, result=_money(emi), result_value=float(emi.quantize(Decimal("0.01"))),
            citation=cit, warnings=warnings), missing
    interest = amount * rate / 100 * months / 12
    steps = [
        f"Active rule rate: {_num(rate)}% per year ({src}).",
        f"Principal = {_money(amount)}; period = {_num(months)} month(s) = {_num(months / 12)} year(s).",
        f"Simple interest = {_money(amount)} × {_num(rate)}% × {_num(months / 12)} = {_money(interest)}.",
    ]
    return Calculation(
        kind="interest", formula="interest = principal × annual_rate% × years (simple)",
        inputs={"principal": float(amount), "annual_rate_percent": float(rate), "months": float(months), "source": src},
        steps=steps, result=_money(interest), result_value=float(interest.quantize(Decimal("0.01"))),
        citation=cit, warnings=warnings), missing


def find_rate_tenure(app_store: AppStore, doc_ids: set[str]) -> Decimal | None:
    for ch in app_store.all_chunks():
        if ch.doc_id not in doc_ids:
            continue
        for s in ch.sentences:
            if "loan tenure" in subjects_in(s.text):
                for unit, val, _ in typed_values(s.text):
                    if unit == "duration:month":
                        return Decimal(str(val))
    return None
