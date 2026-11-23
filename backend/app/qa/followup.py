"""Zero-guessing conversational layer: calculation slot-filling and safe follow-up rewriting.

Hard rule: previous chat turns are NEVER evidence. This module only produces a *question string* (and
optionally a clarification card). That string then goes through Gates 1-4 against stored PDF chunks like
any other question; history text is never passed to the claim-drafting prompt, never cited and never quoted.

Deterministic first:
  1. Calculation slot-filling  - a calculation request that lacks the principal / period is answered with the
     verified active rate plus a `clarification_needed` card; the user's reply (chat or inline form) is merged
     into one standalone calculation question for the deterministic Decimal calculator.
  2. Follow-up rewriting       - only for clearly elliptical follow-ups, only from the last 2 turns; rule
     templates first, then one tiny qwen call (<=64 tokens, temperature 0) whose output is sanity-checked.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation

from app.calculator.service import (
    calc_kind,
    is_calculation_intent,
    lookup_active_rate,
    missing_inputs,
    parse_amount,
    parse_months,
)
from app.contradictions.detector import subjects_in
from app.core.logging import get_logger
from app.core.store import AppStore
from app.models.schemas import ChatTurn, ClarificationNeeded, MissingField
from app.verification.numeric import NUMBER_PATTERN, parse_amount_value

logger = get_logger(__name__)

MAX_HISTORY_TURNS = 2
KINDS = {"late_fee", "interest", "emi"}

_TOPIC_PHRASE = {"late_fee": "late payment penalty", "interest": "interest", "emi": "EMI"}
_LOOKUP_QUESTION = {
    "late_fee": "What is the late payment fee under the latest active rule?",
    "interest": "What is the interest rate under the latest active rule?",
    "emi": "What is the interest rate under the latest active rule?",
}
_FIELD_META = {
    "late_fee": {"principal": ("Overdue Amount (₹)", "50000"), "months": ("Months Overdue", "2")},
    "interest": {"principal": ("Principal Amount (₹)", "50000"), "months": ("Period (Months)", "12")},
    "emi": {"principal": ("Loan Amount (₹)", "500000"), "months": ("Tenure (Months)", "24")},
}


@dataclass
class TurnPlan:
    pipeline_question: str                      # the only text that reaches Gates 1-4
    rewritten_question: str | None = None       # shown to the user as "Resolved follow-up"
    pending: dict | None = None                 # calculation still missing user inputs after this turn
    notes: list[str] = field(default_factory=list)


# ----------------------------------------------------------------------------- slot filling
_INTERROGATIVE_START = re.compile(r"^\s*(?:what|which|who|whom|when|where|why|how|is|are|does|do|can|could|will|should|tell|explain|list|state)\b", re.I)
_PERIOD_SPAN = re.compile(r"\d+(?:\.\d+)?\s*(?:day|week|month|year)s?\b", re.I)
_AMOUNT_SPAN = re.compile(r"(?:₹|\brs\.?|\binr|\brupees?)\s*" + NUMBER_PATTERN + r"\s*(?:lakhs?|lacs?|crores?)?", re.I)
_BARE_NUMBER = re.compile(r"(?<![\w.])(" + NUMBER_PATTERN + r")\s*(lakhs?|lacs?|crores?)?(?![\w%])", re.I)


def _dec(v) -> Decimal | None:
    try:
        d = Decimal(str(v))
        return d if d > 0 else None
    except (InvalidOperation, ValueError):
        return None


def parse_slots(reply: str, missing: list[str]) -> dict[str, Decimal]:
    """Values for the still-missing slots found in a short reply like 'Rs 50,000 for 2 months' / '50000 for 2'."""
    out: dict[str, Decimal] = {}
    amt, months = parse_amount(reply), parse_months(reply)
    if "principal" in missing and amt is not None:
        out["principal"] = amt
    if "months" in missing and months is not None:
        out["months"] = months
    rest = _PERIOD_SPAN.sub(" ", _AMOUNT_SPAN.sub(" ", reply))
    bare = [Decimal(str(parse_amount_value(m.group(1), m.group(2)))) for m in _BARE_NUMBER.finditer(rest)]
    unfilled = [k for k in missing if k not in out]
    if bare and len(bare) >= len(unfilled):  # a lone bare number is ambiguous when 2 slots are open: never guess
        for key in unfilled:  # bare numbers fill the open slots in order (principal first)
            out[key] = bare.pop(0)
    return {k: v for k, v in out.items() if v > 0}


def _is_slot_reply(reply: str, parsed: dict) -> bool:
    words = reply.split()
    if not parsed or len(words) > 14:
        return False
    if _INTERROGATIVE_START.match(reply) or is_calculation_intent(reply):
        return False  # a real question / a full new calculation request is handled as a normal question
    return True


def _fmt_num(v: Decimal) -> str:
    return f"{int(v):,}" if v == v.to_integral_value() else f"{v.normalize():f}"


def _merge_question(kind: str, known: dict[str, Decimal]) -> str:
    """Deterministic standalone calculation question from verified-by-parse inputs."""
    q = f"Calculate the {_TOPIC_PHRASE[kind]}"
    if "principal" in known:
        q += f" on Rs {_fmt_num(known['principal'])}"
    if "months" in known:
        n = known["months"]
        unit = "month" if n == 1 else "months"
        q += f" for {_fmt_num(n)} {unit}"
    return q + " under the latest active rule."


def _pending_from_history(history: list[ChatTurn]) -> dict | None:
    if not history:
        return None
    p = history[-1].pending_calculation
    if not isinstance(p, dict) or p.get("kind") not in KINDS:
        return None
    missing = [k for k in p.get("missing", []) if k in ("principal", "months")]
    if not missing:
        return None
    known = {k: d for k in ("principal", "months") if (d := _dec((p.get("known") or {}).get(k))) is not None}
    return {"kind": p["kind"], "missing": missing, "known": known, "base_question": str(p.get("base_question") or "")}


def _pending_dict(kind: str, missing: list[str], known: dict[str, Decimal], base_question: str) -> dict:
    plain = lambda v: str(int(v)) if v == v.to_integral_value() else f"{v.normalize():f}"  # noqa: E731
    return {"kind": kind, "missing": missing, "known": {k: plain(v) for k, v in known.items()}, "base_question": base_question}


def _slot_fill(question: str, history: list[ChatTurn]) -> TurnPlan | None:
    """Turn 2 of a calculation: merge the user's reply into the pending calculation."""
    pend = _pending_from_history(history)
    if pend is None:
        return None
    parsed = parse_slots(question, pend["missing"])
    if not _is_slot_reply(question, parsed):
        return None
    known = {**pend["known"], **parsed}
    still = [k for k in pend["missing"] if k not in known]
    if still:  # partial reply: ask only for what is still missing, keep what we have
        return TurnPlan(pipeline_question=_LOOKUP_QUESTION[pend["kind"]],
                        pending=_pending_dict(pend["kind"], still, known, pend["base_question"]),
                        notes=["slot_fill_partial"])
    merged = _merge_question(pend["kind"], known)
    return TurnPlan(pipeline_question=merged, rewritten_question=merged, notes=["slot_fill_complete"])


def _calc_without_inputs(question: str) -> TurnPlan | None:
    """Turn 1: 'Calculate my late payment penalty ...' with no amount / period -> verified rate + ask, never guess."""
    if not is_calculation_intent(question):
        return None
    missing = missing_inputs(question)
    if not missing:
        return None  # complete request: normal pipeline + deterministic calculator
    kind = calc_kind(question)
    known = {}
    if (a := parse_amount(question)) is not None:
        known["principal"] = a
    if (m := parse_months(question)) is not None:
        known["months"] = m
    return TurnPlan(pipeline_question=_LOOKUP_QUESTION[kind], pending=_pending_dict(kind, missing, known, question),
                    notes=["calculation_inputs_missing"])


def build_clarification(plan: TurnPlan, app_store: AppStore) -> ClarificationNeeded | None:
    """The card. Only produced when a verified active rate exists (otherwise there is nothing to calculate with)."""
    if not plan.pending:
        return None
    kind = plan.pending["kind"]
    rate = lookup_active_rate(app_store, kind)
    if rate is None:
        return None
    meta = _FIELD_META[kind]
    fields = [MissingField(key=k, label=meta[k][0], placeholder=meta[k][1]) for k in plan.pending["missing"]]
    known = plan.pending.get("known") or {}
    have = ", ".join(f"{k} = {v}" for k, v in known.items())
    msg = (f"Found active rate ({rate['rate_text']}%/{rate['period']}, {rate['source']}) — "
           "provide the missing inputs to calculate without guessing:")
    if have:
        msg = msg[:-1] + f" (already have: {have}):"
    return ClarificationNeeded(message=msg, missing_fields=fields, base_question=plan.pending["base_question"],
                               pending_calculation=plan.pending)


def slots_reply_text(values: dict[str, str]) -> str:
    """Helper for clients/tests: compose the chat reply an inline form would send."""
    parts = []
    if values.get("principal"):
        parts.append(f"Rs {values['principal']}")
    if values.get("months"):
        parts.append(f"{values['months']} months")
    return " for ".join(parts)


# ----------------------------------------------------------------------------- follow-up rewriting
_CONNECTOR_START = re.compile(
    r"^\s*(?:and\s+what\s+about|what\s+about|how\s+about|and|also|same\s+for|what\s+if|how\s+much\s+if|"
    r"explain\s+more|tell\s+me\s+more|more\s+details?|it|it's|its|that|their|they|this|those|these|then)\b", re.I)
_TOPIC_NOUN = re.compile(
    r"\b(fee|fees|penalty|penalties|charge|charges|interest|rate|rates|grace|period|eligibility|policy|policies|loan|loans|"
    r"emi|tenure|limit|collateral|document|documents|notice|circular|clause|section|amount|deposit|account|kyc|"
    r"foreclosure|closure|prepayment|bounce|processing|apr|premium|claim|coverage|cover)\b", re.I)
_QUALIFIER_START = re.compile(r"^(?:in|for|under|at|on|as\s+of|during|from|after|before|with|without|per)\b", re.I)
_VERSIONISH = re.compile(
    r"^(?:the\s+)?(?:v\d+|version\s*\d+|\S*_v\d+\S*|(?:old|older|previous|earlier|original|latest|current|new|newer|first|second|third)\b.*)$", re.I)


def _words(q: str) -> list[str]:
    return re.findall(r"[\w₹%]+", q)


def is_elliptical(question: str, history: list[ChatTurn]) -> bool:
    """Clearly context-dependent: starts with a connector/pronoun, or is very short with no topic noun."""
    if not history:
        return False
    q = question.strip()
    if not q:
        return False
    words = _words(q)
    if _CONNECTOR_START.match(q):
        return True
    return len(words) < 6 and not _TOPIC_NOUN.search(q) and not subjects_in(q)


def _recent(history: list[ChatTurn]) -> list[ChatTurn]:
    return [t for t in history[-MAX_HISTORY_TURNS:] if (t.question or t.answer_summary)]


def _topic_from_history(history: list[ChatTurn]) -> str | None:
    """A single unambiguous subject from the most recent turn that has one (questions first, then summaries)."""
    for t in reversed(_recent(history)):
        for text in (t.question, t.answer_summary):
            subs = subjects_in(text or "")
            if len(subs) == 1:
                return subs[0]
            if len(subs) > 1:
                return None  # ambiguous -> let the LLM rewriter (or no rewrite) decide
    return None


def _clean_remainder(r: str) -> str:
    return re.sub(r"[?.!\s]+$", "", r.strip())


def _rule_rewrite(question: str, history: list[ChatTurn]) -> str | None:
    q = question.strip()
    m = re.match(r"^(?:and\s+)?(?:what|how)\s+about\s+(.+)$", q, re.I) or re.match(r"^and\s+(.+)$", q, re.I) \
        or re.match(r"^same\s+for\s+(.+)$", q, re.I) or re.match(r"^also\s+(.+)$", q, re.I)
    topic = _topic_from_history(history)
    if m:
        rem = _clean_remainder(m.group(1))
        if not rem:
            return None
        if subjects_in(rem):  # "what about the grace period?"
            rem = re.sub(r"^the\s+", "", rem, flags=re.I)
            return f"What is the {rem}?"
        if topic and _QUALIFIER_START.match(rem):  # "what about in v1?"
            return f"What is the {topic} {rem}?"
        if topic and _VERSIONISH.match(rem):  # "same for v2" / "what about the previous version?"
            bare = re.sub(r"^the\s+", "", rem, flags=re.I)
            qualifier = bare if re.match(r"^(?:v\d|version)", bare, re.I) else "the " + bare
            return f"What is the {topic} in {qualifier}?"
        return None
    if topic and re.match(r"^(?:explain\s+more|tell\s+me\s+more|more\s+details?)\b", q, re.I):
        return f"Explain the {topic} in more detail."
    return None


_NUM = re.compile(r"\d[\d,]*(?:\.\d+)?")


def _llm_rewrite(question: str, history: list[ChatTurn], llm) -> str | None:
    recent = _recent(history)
    if not recent or llm is None:
        return None
    ctx = "\n".join(f"Q: {t.question.strip()[:300]}\nA: {t.answer_summary.strip()[:200]}" for t in recent)
    prompt = (
        "Rewrite the FOLLOW-UP as ONE standalone question that can be understood without the chat. "
        "Resolve pronouns and missing subjects using the chat. Do NOT answer it. Do NOT add numbers, names or facts that "
        "are not in the chat or the follow-up. If it is already standalone, return it unchanged.\n"
        f"CHAT:\n{ctx}\nFOLLOW-UP: {question.strip()}\n"
        'Return JSON only: {"standalone_question": "<one line>"}'
    )
    try:
        fn = getattr(llm, "generate_json_limited", None)
        raw = fn(prompt, max_tokens=64) if fn else llm.generate_json(prompt)
    except Exception as e:  # model down -> no rewrite, never a guess
        logger.warning("Follow-up rewrite LLM failed: %s", e)
        return None
    cand = str((raw or {}).get("standalone_question") or "").strip() if isinstance(raw, dict) else ""
    return cand if _valid_rewrite(cand, question, recent) else None


def _valid_rewrite(cand: str, question: str, recent: list[ChatTurn]) -> bool:
    if not cand or "\n" in cand or len(cand) > 240 or len(_words(cand)) < 3:
        return False
    allowed = set(_NUM.findall(question)) | {n for t in recent for n in _NUM.findall(t.question or "")}
    return all(n in allowed for n in _NUM.findall(cand))  # no numbers smuggled in from answer summaries


def rewrite_followup(question: str, history: list[ChatTurn], llm=None) -> tuple[str | None, str]:
    """(rewritten, method). Standalone questions and empty history are never touched."""
    if not is_elliptical(question, history):
        return None, "none"
    r = _rule_rewrite(question, history)
    if r and r.strip().lower() != question.strip().lower():
        return r, "rule"
    r = _llm_rewrite(question, history, llm)
    if r and r.strip().lower() != question.strip().lower():
        return r, "llm"
    return None, "none"


# ----------------------------------------------------------------------------- entry point
def plan_turn(question: str, history: list[ChatTurn] | None, llm=None) -> TurnPlan:
    history = list(history or [])[-MAX_HISTORY_TURNS:]
    plan = _slot_fill(question, history)
    if plan is not None:
        return plan
    plan = _calc_without_inputs(question)
    if plan is not None:
        return plan
    rewritten, method = rewrite_followup(question, history, llm)
    if rewritten:
        # A rewritten follow-up can itself be a calculation request with missing inputs.
        sub = _calc_without_inputs(rewritten)
        if sub is not None:
            sub.rewritten_question = rewritten
            return sub
        return TurnPlan(pipeline_question=rewritten, rewritten_question=rewritten, notes=[f"rewrite_{method}"])
    return TurnPlan(pipeline_question=question)
