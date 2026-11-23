"""Soft-wrap line reflow (+ multi-line bbox union) and LLM JSON key normalisation / missing-`claims` retry."""
from __future__ import annotations

import json
from pathlib import Path

import pymupdf
import pytest

import app.qa.llm as llm_mod
from app.core.config import settings
from app.core.store import AppStore
from app.ingestion.chunker import chunk_pages
from app.ingestion.parser import _head_tail_rects, parse_pdf, reflow_blocks
from app.qa.llm import CONCISE_RETRY_SUFFIX, OllamaLLMProvider, normalize_claim_keys


# ------------------------------------------------------------------------------- reflow (pure function)
def _b(text, y, kind="paragraph", x=72.0, h=14.0):
    return {"block_type": kind, "text": text, "_rect": pymupdf.Rect(x, y, x + 400, y + h), "_bwords": [text], "_nwords": [text]}


def test_reflow_joins_soft_wrapped_lines_and_fixes_hyphen_breaks():
    out = reflow_blocks([_b("it shall compensate the", 100), _b("borrower at the rate of ₹5,000/- for each day of delay.", 116)])
    assert [b["text"] for b in out] == ["it shall compensate the borrower at the rate of ₹5,000/- for each day of delay."]
    assert out[0]["_rect"] == pymupdf.Rect(72, 100, 472, 130)  # union box; words kept for the bbox search
    assert len(out[0]["_bwords"]) == 2
    (hy,) = reflow_blocks([_b("no penal interest for non-", 100), _b("compliance of the terms.", 116)])
    assert hy["text"] == "no penal interest for non-compliance of the terms."
    (slash,) = reflow_blocks([_b("at the rate of ₹5,000/-", 100), _b("for each day of delay.", 116)])
    assert slash["text"] == "at the rate of ₹5,000/- for each day of delay."  # '/-' is not a word break


def test_reflow_keeps_paragraphs_bullets_numbered_items_headings_and_tables_intact():
    para = [_b("First paragraph ends here.", 100), _b("Second paragraph starts here", 118), _b("and wraps onto a second line.", 134)]
    assert [b["text"] for b in reflow_blocks(para)] == ["First paragraph ends here.", "Second paragraph starts here and wraps onto a second line."]
    for start in ("• bullet item", "- dash item", "(i) roman item", "(a) letter item", "3. numbered item", "2.1 Sub item", "a) letter paren"):
        out = reflow_blocks([_b("the previous line has no full stop", 100), _b(start, 116)])
        assert [b["text"] for b in out] == ["the previous line has no full stop", start], start
    assert len(reflow_blocks([_b("A line ending with a colon:", 100), _b("next line", 116)])) == 2
    assert len(reflow_blocks([_b("a wrapped line", 100), _b("Heading text", 116, kind="heading")])) == 2
    assert len(reflow_blocks([_b("a wrapped line", 100), {"block_type": "table", "text": "x", "rows": []}])) == 2
    assert len(reflow_blocks([_b("a wrapped line", 100), _b("far below", 200)])) == 2  # big vertical gap = new paragraph
    assert len(reflow_blocks([_b("a wrapped line", 100), _b("other column", 116, x=320)])) == 2  # different column
    assert len(reflow_blocks([_b("a wrapped line", 100), _b("double spaced line", 121)])) == 1  # ~7pt gap (RBI letters)


# ------------------------------------------------------------------------------- real PDF + bbox union
def _wrapped_pdf(path: Path) -> None:
    doc = pymupdf.open()
    pg = doc.new_page()
    pg.insert_textbox(pymupdf.Rect(72, 72, 250, 400),
                      "In case where the delay is attributable to the RE, it shall compensate the borrower at the rate of "
                      "5,000 for each day of delay and ensure full compliance with the directions.",
                      fontsize=11, fontname="helv")
    pg.insert_textbox(pymupdf.Rect(72, 300, 500, 400), "(i) First list item stays alone.\n(ii) Second list item stays alone.", fontsize=11)
    doc.save(str(path))


def test_wrapped_pdf_sentence_is_whole_and_highlight_box_covers_every_line(tmp_path):
    pdf = tmp_path / "wrapped.pdf"
    _wrapped_pdf(pdf)
    (page,) = parse_pdf(pdf)
    paras = [b for b in page["blocks"] if b["block_type"] == "paragraph"]
    wrapped = next(b for b in paras if "attributable" in b["text"])
    assert "\n" not in wrapped["text"] and "compensate the borrower at the rate" in wrapped["text"]
    chunks = chunk_pages("w", "wrapped.pdf", [page])
    sent = next(s for c in chunks for s in c.sentences if "compensate the borrower" in s.text)
    assert sent.text.startswith("In case where") and sent.text.endswith("directions.")
    assert sent.bbox is not None and sent.bbox.y1 - sent.bbox.y0 > 35  # >= 3 wrapped lines, one union box
    assert sent.bbox.x0 < 80 and sent.bbox.x1 > 200
    items = [t for t in (s.text for c in chunks for s in c.sentences) if "list item" in t]
    assert len(items) >= 2 and all(t.startswith("(") for t in items)  # list items were not glued together


def test_head_tail_union_when_full_sentence_search_cannot_match(tmp_path):
    pdf = tmp_path / "wrapped.pdf"
    _wrapped_pdf(pdf)
    page = pymupdf.open(str(pdf))[0]
    sent = ("In case where the delay is attributable to the RE, it shall compensate the borrower at the rate of "
            "5,000 for each day of delay and ensure full compliance with the directions.")
    rects = _head_tail_rects(page, sent, pymupdf.Rect(60, 60, 260, 200))
    assert len(rects) == 2 and rects[0].y0 < rects[1].y0  # first words on line 1, last words on the last line
    union = rects[0] | rects[1]
    assert union.height > 35
    assert _head_tail_rects(page, "too short to split", None) == []


# ------------------------------------------------------------------------------- real RBI PDFs
RBI_DIR = Path(__file__).resolve().parents[2] / "data" / "documents"
NOTI = next(iter(RBI_DIR.glob("NOTI*.pdf")), None)
PENAL = next(iter(RBI_DIR.glob("PENALCHARGES*.pdf")), None)
FAIR = next(iter(RBI_DIR.glob("FAIRLENDING*.pdf")), None)


@pytest.mark.skipif(not (NOTI and PENAL and FAIR), reason="real RBI PDFs not present")
def test_real_rbi_sentences_are_whole(monkeypatch, tmp_path):
    from app.ingestion.service import ingest_pdf_file

    monkeypatch.setattr(settings, "data_dir", str(tmp_path))
    st = AppStore(workspace="byo_private")
    for f in (FAIR, NOTI, PENAL):
        ingest_pdf_file(f, app_store=st)
    texts = [s["text"] for s in st.sentence_index.values()]
    assert ("In case where the delay is attributable to the RE, it shall compensate the borrower at the rate of "
            "₹5,000/- for each day of delay.") in texts
    (e,) = st.amendment_edges
    assert e.evidence_quote.endswith("it has been decided to extend the timeline for implementation of the instructions by three months.")
    assert e.evidence_quote.startswith("However, considering that") and e.effective_date == "2024-04-01"


# ------------------------------------------------------------------------------- JSON synonym keys + retry
CLAIM = {"claim": "The late payment fee is 2% per month.", "source_ids": ["d_p1_c1#s0"]}


def test_normalize_claim_keys_only_relabels_valid_claim_objects():
    for key in ("response", "answers", "results", "items"):
        out = normalize_claim_keys({key: [CLAIM, {"claim": "no sources here"}, {"source_ids": ["x"]}, "junk"]})
        assert out["claims"] == [CLAIM] and key not in out and out["missing_evidence"] == []  # invalid items dropped, never repaired
    kept = normalize_claim_keys({"response": [{"text": "t", "sources": ["a#s0"]}], "missing_evidence": ["m"]})
    assert kept["missing_evidence"] == ["m"] and len(kept["claims"]) == 1
    assert normalize_claim_keys({"claims": [CLAIM]}) == {"claims": [CLAIM]}  # already correct: untouched
    wrong = {"response": [{"para": "These instructions shall come into effect from January 1, 2024.", "page": 1}]}
    assert normalize_claim_keys(wrong) == wrong  # not claim-like -> left alone (and will trigger the retry)
    assert normalize_claim_keys({"translations": [{"claim_id": "c1", "hindi": "x"}]}) == {"translations": [{"claim_id": "c1", "hindi": "x"}]}


class _Client:
    posts: list[dict] = []
    responses: list[str] = []

    def __init__(self, *a, **k): ...
    def __enter__(self): return self
    def __exit__(self, *a): return False

    def post(self, url, json):  # noqa: A002
        _Client.posts.append(json)
        body = _Client.responses.pop(0)
        return type("R", (), {"raise_for_status": lambda s: None, "json": lambda s: {"response": body}})()


CLAIM_PROMPT = 'OUTPUT SCHEMA:\n{"claims":[{"claim_id":"c1"}]}\nQUESTION: q'


def test_missing_claims_key_triggers_one_retry_with_shape_reminder(monkeypatch):
    monkeypatch.setattr(llm_mod.httpx, "Client", _Client)
    good = json.dumps({"claims": [CLAIM], "missing_evidence": []})

    _Client.posts, _Client.responses = [], [json.dumps({"response": [{"para": "x", "page": 1}]}), good]  # wrong shape, not claim-like
    out = OllamaLLMProvider().generate_json(CLAIM_PROMPT)
    assert out["claims"] == [CLAIM] and len(_Client.posts) == 2
    assert _Client.posts[1]["prompt"] == CLAIM_PROMPT + CONCISE_RETRY_SUFFIX
    assert '{"claims": [{"claim": "...", "source_ids": ["..."]}], "missing_evidence": [...]}' in _Client.posts[1]["prompt"]

    _Client.posts, _Client.responses = [], [json.dumps({"response": [CLAIM]})]  # synonym key: normalised, NO retry
    out = OllamaLLMProvider().generate_json(CLAIM_PROMPT)
    assert out["claims"] == [CLAIM] and len(_Client.posts) == 1

    _Client.posts, _Client.responses = [], ['{"something": 1}', '{"still": "wrong"}']  # retry also wrong -> no invented claims
    out = OllamaLLMProvider().generate_json(CLAIM_PROMPT)
    assert len(_Client.posts) == 2 and not out.get("claims")

    _Client.posts, _Client.responses = [], [json.dumps({"claims": [], "missing_evidence": ["nothing found"]})]  # valid abstention: untouched
    assert OllamaLLMProvider().generate_json(CLAIM_PROMPT)["missing_evidence"] == ["nothing found"] and len(_Client.posts) == 1

    _Client.posts, _Client.responses = [], [json.dumps({"translations": [{"claim_id": "c1", "hindi": "x"}]})]  # other prompt shapes: no retry
    OllamaLLMProvider().generate_json("Translate these claims to Hindi")
    assert len(_Client.posts) == 1


# ------------------------------------------------------------------------------- bounded repair round
FEE = "2% per month applies on the overdue amount"
GRACE = "grace period of 15 days"


def _text(st, needle):
    return next(s.text for c in st.all_chunks() for s in c.sentences if needle in s.text)


def _claim(cid, text, sid):
    return {"claim_id": cid, "text": text, "claim_type": "factual", "source_ids": [sid]}


def _run(responses_for):
    """responses_for(st, sid) -> list of LLM JSON responses (sid resolves a sentence id by substring)."""
    from app.qa.llm import FakeLLMProvider
    from app.qa.service import ask_question
    from app.retrieval.embeddings import FakeEmbeddingProvider
    from app.retrieval.reranker import FakeRerankerProvider
    from app.verification.nli import FakeNLIProvider
    from tests.helpers import sample_store

    st = sample_store()
    settings.rerank_abstain_threshold = 0.0
    sid = lambda needle: next(s.sentence_id for c in st.all_chunks() for s in c.sentences if needle in s.text)  # noqa: E731
    llm = FakeLLMProvider(responses=responses_for(st, sid))
    resp = ask_question(question="What is the late payment fee under the latest active rule?", app_store=st,
                        embedding_provider=FakeEmbeddingProvider(), reranker_provider=FakeRerankerProvider(),
                        nli_provider=FakeNLIProvider(), llm_provider=llm)
    return resp, llm, sid


def _first_round_bad(st, sid):  # numeric mismatch vs its quote: blocked at Gate 3
    return {"claims": [_claim("c1", "The late payment fee is 9% per month.", sid(FEE))], "missing_evidence": []}


def test_repair_round_recovers_after_total_gate3_rejection_and_keeps_the_rejection_visible():
    def responses(st, sid):
        return [_first_round_bad(st, sid), {"claims": [_claim("y", _text(st, GRACE), sid(GRACE))], "missing_evidence": []}]

    resp, llm, sid = _run(responses)
    assert len(llm.calls) == 2 and "REPAIR ROUND" in llm.calls[1] and sid(FEE) in llm.calls[1]  # rejected id is named as a hint
    assert [c.text for c in resp.claims if c.citations[0].sentence_id == sid(GRACE)] and resp.faithfulness_pct == 100.0
    assert resp.blocked_claims_count == 1 and resp.blocked_claims[0].text == "The late payment fee is 9% per month."


def test_repair_round_never_resubmits_an_identical_rejected_claim_and_gates_still_apply():
    def responses(st, sid):
        return [_first_round_bad(st, sid), {"claims": [_claim("y", "The late payment fee is 9% per month.", sid(FEE))], "missing_evidence": []}]

    resp, llm, _ = _run(responses)
    assert len(llm.calls) == 2 and not resp.claims and resp.status == "abstained"  # no unverified answer slips through
    assert "9%" not in resp.answer


def test_no_repair_round_when_something_was_verified():
    def responses(st, sid):
        return [{"claims": [_claim("c1", _text(st, FEE), sid(FEE))], "missing_evidence": []}]

    resp, llm, _ = _run(responses)
    assert resp.claims and len(llm.calls) == 1


def test_repair_round_can_fix_the_wording_over_the_same_sentence():
    def responses(st, sid):
        over = {"claims": [_claim("c1", "The compensation is 9% per month.", sid(FEE))], "missing_evidence": []}
        return [over, {"claims": [_claim("y", _text(st, FEE), sid(FEE))], "missing_evidence": []}]

    resp, llm, sid = _run(responses)
    assert [c.citations[0].sentence_id for c in resp.claims] == [sid(FEE)] and resp.faithfulness_pct == 100.0
    assert resp.blocked_claims_count == 1 and len(llm.calls) == 2
