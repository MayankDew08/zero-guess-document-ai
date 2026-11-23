"""Amendment-aware contradiction detection on unit-typed values.

Only values that carry a unit (%, currency, duration) are compared, and only for the same
canonical subject (late payment fee, grace period, ...). Leading section numbers
("2. Late Payment Fee") are stripped and heading-like fragments are never used as quotes.
Conflicts between a document and the doc that (transitively) supersedes it are NOT
contradictions - they belong to Amendment Chains. Superseded docs are historical and are
not compared against live documents.
"""
from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from itertools import combinations

from app.amendments.graph import is_amendment_pair, superseded_doc_ids
from app.core.store import AppStore
from app.models.schemas import (
    AmendmentEdge,
    BBox,
    Claim,
    Contradiction,
    ContradictionValue,
    RetrievalResult,
)
from app.verification.nli import NLIProvider

_SECTION_NUM_RE = re.compile(r"^\s*\d+(\.\d+)*[\.\)]\s+")
_PERCENT_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(?:%|percent\b|per\s*cent\b)", re.IGNORECASE)
_CURRENCY_RE = re.compile(r"(?:₹|\brs\.?|\binr|\busd|\$)\s*(\d[\d,]*(?:\.\d+)?)", re.IGNORECASE)
_DURATION_RE = re.compile(r"(\d+)[\s-]*(day|week|month|year)s?\b", re.IGNORECASE)

# canonical subject -> (regex, unit types that may be compared for it)
_SUBJECTS: dict[str, tuple[re.Pattern, set[str]]] = {
    "late payment fee": (re.compile(r"late\s+(?:payment\s+)?(?:fee|charge|penalty)|late\s+payment", re.I), {"percent", "currency"}),
    "grace period": (re.compile(r"grace\s+period", re.I), {"duration"}),
    "interest rate": (re.compile(r"interest\s+rate", re.I), {"percent"}),
    "loan tenure": (re.compile(r"\btenure\b|loan\s+term", re.I), {"duration"}),
    "processing fee": (re.compile(r"processing\s+fee", re.I), {"percent", "currency"}),
    "prepayment penalty": (re.compile(r"prepayment\s+(?:penalty|charge|fee)", re.I), {"percent", "currency"}),
    "bounce charge": (re.compile(r"bounce\s+(?:charge|fee)|dishonou?r\s+charge|cheque\s+return", re.I), {"percent", "currency"}),
    "early closure": (re.compile(r"early\s+closure|foreclosure", re.I), {"duration"}),
}


@dataclass
class _Sent:
    sentence_id: str
    chunk_id: str
    doc_id: str
    doc_name: str
    page: int
    text: str
    bbox: BBox | None
    is_table: bool


def strip_section_number(text: str) -> str:
    return _SECTION_NUM_RE.sub("", text or "", count=1).strip()


def looks_like_heading(text: str) -> bool:
    raw = (text or "").strip()
    body = strip_section_number(raw)
    words = body.split()
    if not words:
        return True
    if raw != body and not body.endswith((".", ";", ":")) and len(words) <= 10:
        return True  # "2. Late Payment Fee"
    return len(words) <= 4 and not body.endswith(".") and "|" not in body


def subjects_in(text: str) -> list[str]:
    return [name for name, (rx, _) in _SUBJECTS.items() if rx.search(text or "")]


def typed_values(text: str) -> list[tuple[str, float, str]]:
    """[(unit_key, value, raw)] for %, currency, duration. Bare numbers are ignored."""
    body = strip_section_number(text)
    out: list[tuple[str, float, str]] = []
    for m in _PERCENT_RE.finditer(body):
        out.append(("percent", float(m.group(1)), m.group(0).strip()))
    for m in _CURRENCY_RE.finditer(body):
        out.append(("currency", float(m.group(1).replace(",", "")), m.group(0).strip()))
    for m in _DURATION_RE.finditer(body):
        out.append((f"duration:{m.group(2).lower()}", float(m.group(1)), m.group(0).strip()))
    return out


def _values_for(subject: str, text: str) -> list[tuple[str, float, str]]:
    allowed = _SUBJECTS[subject][1]
    return [v for v in typed_values(text) if v[0].split(":")[0] in allowed]


def _differs(a: float, b: float) -> bool:
    return abs(a - b) / max(abs(a), abs(b), 1e-9) > 0.01


# --------------------------------------------------------------------------------------------
def _store_sentences(app_store: AppStore) -> list[_Sent]:
    out = []
    for ch in app_store.all_chunks():
        for s in ch.sentences:
            out.append(_Sent(s.sentence_id, ch.chunk_id, ch.doc_id, ch.doc_name, ch.page, s.text, s.bbox, ch.chunk_type == "table"))
    return out


def find_conflicts(
    sentences: list[_Sent],
    edges: list[AmendmentEdge],
    only_subjects: set[str] | None = None,
    nli_provider: NLIProvider | None = None,
) -> list[Contradiction]:
    superseded = superseded_doc_ids(edges)
    live = [s for s in sentences if s.doc_id not in superseded and not looks_like_heading(s.text)]
    best: dict[tuple, tuple[int, _Sent, _Sent, str, str, str]] = {}
    by_subject: dict[str, list[tuple[_Sent, list]]] = {}
    for s in live:
        for subj in subjects_in(s.text):
            if only_subjects is not None and subj not in only_subjects:
                continue
            vals = _values_for(subj, s.text)
            if vals:
                by_subject.setdefault(subj, []).append((s, vals))

    for subj, items in by_subject.items():
        for (a, va), (b, vb) in combinations(items, 2):
            if a.doc_id == b.doc_id or is_amendment_pair(a.doc_id, b.doc_id, edges):
                continue
            hit = next(((x, y) for x in va for y in vb if x[0] == y[0] and _differs(x[1], y[1])), None)
            if not hit:
                continue
            docs = tuple(sorted((a.doc_id, b.doc_id)))
            key = (subj, docs, hit[0][0].split(":")[0])
            rank = int(a.is_table) + int(b.is_table)  # prefer prose quotes over table rows
            if key not in best or rank < best[key][0]:
                first, second = (a, b) if a.doc_id <= b.doc_id else (b, a)
                f_raw, s_raw = (hit[0][2], hit[1][2]) if first is a else (hit[1][2], hit[0][2])
                best[key] = (rank, first, second, f_raw, s_raw, subj)

    out: list[Contradiction] = []
    for (subj, _docs, _vtype), (_, a, b, ra, rb, _s) in best.items():
        explanation = (f"Unresolved conflict on '{subj}': {a.doc_name} says {ra} but {b.doc_name} says {rb}, "
                       "and neither document amends or supersedes the other.")
        if nli_provider is not None:
            try:
                sc = nli_provider.predict(premise=strip_section_number(a.text), hypothesis=strip_section_number(b.text))
                explanation += f" (NLI contradiction p={sc.get('contradiction', 0.0):.2f})"
            except Exception:
                pass
        out.append(Contradiction(
            contradiction_id=f"ctr_{uuid.uuid4().hex[:8]}",
            subject=subj,
            conflict_type="number",
            severity="high",
            status="confirmed",
            explanation=explanation,
            values=[_to_value(a, ra), _to_value(b, rb)],
        ))
    return out


def _to_value(s: _Sent, raw: str) -> ContradictionValue:
    return ContradictionValue(doc_id=s.doc_id, doc_name=s.doc_name, page=s.page, chunk_id=s.chunk_id,
                              sentence_id=s.sentence_id, quote=s.text, bbox=s.bbox, normalized_value=raw)


def scan_corpus_contradictions(app_store: AppStore, nli_provider: NLIProvider | None = None,
                               doc_ids: list[str] | None = None) -> list[Contradiction]:
    """Corpus-wide scan used by GET /api/contradictions."""
    sents = _store_sentences(app_store)
    if doc_ids:
        sents = [s for s in sents if s.doc_id in set(doc_ids)]
    return find_conflicts(sents, app_store.amendment_edges, nli_provider=nli_provider)


def detect_contradictions(
    claims: list[Claim],
    retrieval: RetrievalResult,
    amendment_edges: list[AmendmentEdge],
    nli_provider: NLIProvider | None = None,
    app_store: AppStore | None = None,
    question: str = "",
) -> list[Contradiction]:
    """Conflicts relevant to this question (subjects named in the question or in verified claims).

    Scans the whole corpus when `app_store` is given (so a conflicting notice is found even if it
    was not in the top-k), otherwise only the retrieved chunks and cited sentences."""
    relevant = set(subjects_in(question))
    if not relevant:  # question names no known subject: fall back to what the verified claims discuss
        for c in claims:
            relevant.update(subjects_in(c.text))
    if not relevant:
        return []
    if app_store is not None:
        sentences = _store_sentences(app_store)
    else:
        sentences = []
        for r in retrieval.chunks:
            ch = r.chunk
            sentences += [_Sent(s.sentence_id, ch.chunk_id, ch.doc_id, ch.doc_name, ch.page, s.text, s.bbox, ch.chunk_type == "table") for s in ch.sentences]
        seen = {s.sentence_id for s in sentences}
        for c in claims:
            for cit in c.citations:
                if cit.sentence_id not in seen:
                    sentences.append(_Sent(cit.sentence_id, cit.chunk_id, cit.doc_id, cit.doc_name, cit.page, cit.quote, cit.bbox, False))
    found = find_conflicts(sentences, amendment_edges, only_subjects=relevant, nli_provider=nli_provider)
    for ctr in found:
        sids = {v.sentence_id for v in ctr.values}
        ctr.affected_claim_ids = [c.claim_id for c in claims if sids & {cit.sentence_id for cit in c.citations}]
    return found
