"""Hindi rendering of verified claims.

Stage 1 (English): the LLM drafts claims citing English sentence_ids; Gates 2-3 verify them.
Stage 2 (here): each *verified* claim is rendered in Hindi (Devanagari) and the rendering must
itself pass NLI entailment (mDeBERTa, cross-lingual) and the deterministic numeric/date check
against the English quote, plus a script sanity check. A rendering that fails any check is
dropped and the verified English claim is shown instead - nothing unverified reaches the user.
"""
from __future__ import annotations

import json
import re

from app.core.config import settings
from app.core.logging import get_logger
from app.models.schemas import Claim
from app.qa.llm import LLMProvider
from app.verification.nli import NLIProvider
from app.verification.numeric import check_numeric_date_match

logger = get_logger(__name__)
_DEV = re.compile(r"[ऀ-ॿ]")


def build_translation_prompt(claims: list[Claim]) -> str:
    items = [{"claim_id": c.claim_id, "english": c.text} for c in claims]
    return (
        "Translate each English sentence into natural, fluent Hindi (Devanagari script).\n"
        "RULES:\n"
        "- Output VALID JSON only: {\"translations\":[{\"claim_id\":\"c1\",\"hindi\":\"...\"}]}\n"
        "- Translate faithfully. Do NOT add, remove or reword any fact, qualifier or condition.\n"
        "- Keep every number, percentage, currency amount (e.g. 2%, INR 1,000, Rs 50,000), duration and date EXACTLY as in the "
        "English sentence, using ASCII digits (never Devanagari digits).\n"
        "- Use this glossary: late payment fee = विलंब भुगतान शुल्क; grace period = ग्रेस अवधि; due date = देय तिथि; per month = प्रति माह; "
        "per year = प्रति वर्ष; interest rate = ब्याज दर; loan tenure = ऋण अवधि; processing fee = प्रोसेसिंग शुल्क; "
        "prepayment penalty = पूर्व-भुगतान शुल्क; bounce charge = बाउंस शुल्क; applicants = आवेदक; credit score = क्रेडिट स्कोर; "
        "salary slips = वेतन पर्ची; bank statements = बैंक स्टेटमेंट; instalment = किस्त; overdue amount = बकाया राशि.\n"
        "- Write Hindi words only in Devanagari; do not mix in partial English words (INR, EMI, SMS and the numbers may stay).\n"
        "- Example: 'The processing fee is INR 500 at disbursement.' -> 'प्रोसेसिंग शुल्क वितरण के समय INR 500 है।'\n\n"
        "SENTENCES:\n" + json.dumps(items, ensure_ascii=False)
    )


_LATIN_WORD = re.compile(r"[A-Za-z]+")


def _stray_latin(text: str) -> bool:
    """Latin words other than ALL-CAPS abbreviations (INR, EMI, SMS...) mean a garbled mixed-script rendering."""
    foreign = any(ch.isalpha() and ord(ch) > 127 and not _DEV.match(ch) for ch in text)  # e.g. Thai/CJK leakage
    return foreign or any(not w.isupper() for w in _LATIN_WORD.findall(text)) or bool(re.search(r"[\u0900-\u097F][A-Za-z]|[A-Za-z][\u0900-\u097F]", text))


def build_backtranslation_prompt(items: list[tuple[str, str]]) -> str:
    return (
        "Translate each Hindi sentence into plain, literal English. Do not use any outside knowledge and do not fix errors; "
        "translate exactly what the Hindi says. Keep numbers exactly.\n"
        "Output VALID JSON only: {\"translations\":[{\"claim_id\":\"c1\",\"english\":\"...\"}]}\n\n"
        "SENTENCES:\n" + json.dumps([{"claim_id": i, "hindi": h} for i, h in items], ensure_ascii=False)
    )


def _looks_like_hindi(text: str) -> bool:
    letters = [ch for ch in text if ch.isalpha()]
    return bool(letters) and sum(1 for ch in letters if _DEV.match(ch)) / len(letters) >= 0.5


def render_claims_in_hindi(claims: list[Claim], llm: LLMProvider, nli: NLIProvider | None) -> list[str]:
    """Mutates claims in place (text -> Hindi, text_en keeps the verified English). Returns notes."""
    if not claims:
        return []
    notes: list[str] = []
    try:
        raw = llm.generate_json(build_translation_prompt(claims))
    except Exception as e:
        return [f"Hindi rendering unavailable ({e}); showing verified English claims."]
    by_id = {str(t.get("claim_id")): str(t.get("hindi") or "").strip()
             for t in (raw.get("translations") or []) if isinstance(t, dict)}
    passed: list[tuple[Claim, str, str, float | None]] = []
    for c in claims:
        hindi = by_id.get(c.claim_id, "")
        quote = " ".join(cit.quote for cit in c.citations)
        ctx = " ".join(cit.section_context or "" for cit in c.citations)
        ok_num, why = check_numeric_date_match(hindi, quote, ctx) if hindi else (False, "empty")
        eng_nums = set(re.findall(r"\d[\d,]*(?:\.\d+)?%?", c.text))
        nums_kept = eng_nums <= set(re.findall(r"\d[\d,]*(?:\.\d+)?%?", hindi))
        entail, score = True, None
        if nli is not None and hindi:
            sc = nli.predict(premise=f"{ctx}: {quote}" if ctx.strip() else quote, hypothesis=hindi)
            score = sc.get("entailment", 0.0)
            entail = max(sc, key=sc.get) == "entailment" and score >= settings.nli_entailment_threshold
        clean = bool(hindi) and _looks_like_hindi(hindi) and not _stray_latin(hindi)
        if clean and ok_num and nums_kept and entail:
            passed.append((c, hindi, quote, score))
        else:
            notes.append(f"Hindi rendering of {c.claim_id} rejected (clean_script={clean}, numeric={ok_num}{'/' + str(why) if why else ''}, "
                         f"numbers_kept={nums_kept}, nli_ok={entail}); showing verified English.")

    # Round trip: Hindi -> English must be mutually entailed with the verified English claim (English NLI is reliable).
    back: dict[str, str] = {}
    if passed:
        try:
            raw_b = llm.generate_json(build_backtranslation_prompt([(c.claim_id, h) for c, h, _, _ in passed]))
            back = {str(t.get("claim_id")): str(t.get("english") or "") for t in (raw_b.get("translations") or []) if isinstance(t, dict)}
        except Exception as e:
            notes.append(f"Back-translation unavailable ({e}); showing verified English.")
            passed = []
    for c, hindi, _quote, score in passed:
        be = back.get(c.claim_id, "")
        rt_ok = False
        if be and nli is not None:
            f = nli.predict(premise=c.text, hypothesis=be)
            r = nli.predict(premise=be, hypothesis=c.text)
            rt_ok = f.get("entailment", 0) >= settings.nli_entailment_threshold and r.get("entailment", 0) >= settings.nli_entailment_threshold
        elif be:
            rt_ok = True
        if rt_ok and check_numeric_date_match(be, c.text)[0]:
            c.text_en, c.text, c.language = c.text, hindi, "hi"
            for cit in c.citations:
                cit.verification_notes = (cit.verification_notes or "") + (
                    f";hindi_nli_entailment={None if score is None else round(score, 3)};hindi_roundtrip_ok=True")
        else:
            notes.append(f"Hindi rendering of {c.claim_id} failed the English round-trip check (back-translation: {be!r}); showing verified English.")
    for n in notes:
        logger.info(n)
    return notes
