"""Truncated-JSON salvage + real RBI circular id / timeline-extension amendment linking."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import app.qa.llm as llm_mod
from app.amendments.graph import (
    build_amendment_chains,
    extract_amendment_edges,
    extract_reference_ids,
)
from app.core.config import settings
from app.core.store import AppStore
from app.models.schemas import Chunk, Sentence
from app.qa.llm import (
    CONCISE_RETRY_SUFFIX,
    OllamaLLMProvider,
    _parse_json,
    salvage_truncated_claims,
)
from app.qa.prompt import build_claim_prompt
from app.qa.service import _parse_draft

# ------------------------------------------------------------------ truncated JSON salvage
FULL = {"claims": [{"claim_id": "c1", "text": "Penal charges shall not be capitalised.", "source_ids": ["d_p1_c1#s0"]},
                   {"claim": 'The fee is "2%" per month (a {brace} too).', "source_ids": ["d_p1_c1#s1"]}], "missing_evidence": []}


def test_salvage_keeps_complete_claims_and_drops_the_cut_off_one():
    raw = json.dumps(FULL)
    cut = raw[: raw.index('"source_ids": ["d_p1_c1#s1"]') + 10]  # dies inside the 2nd claim's source_ids
    out = salvage_truncated_claims(cut)
    assert out and [c.get("text") or c.get("claim") for c in out["claims"]] == ["Penal charges shall not be capitalised."]
    assert out["salvaged_truncated"] and "cut off" in out["missing_evidence"][0]

    # cut AFTER the 2nd object but before the closing ']}': both complete claims survive, braces/quotes in strings are safe
    cut2 = raw[: raw.index('], "missing_evidence"')]
    out2 = salvage_truncated_claims(cut2)
    assert out2 and len(out2["claims"]) == 2 and out2["claims"][1]["claim"].startswith("The fee is")
    assert salvage_truncated_claims('{"claims": [{"text": "half a cla') is None  # nothing complete -> no salvage
    assert salvage_truncated_claims('{"claims": [{"text": "no sources here"}') is None  # unsourced objects are not claims
    assert salvage_truncated_claims("not json at all") is None


def test_parse_json_pipeline_uses_salvage_and_leaves_valid_output_untouched():
    raw = json.dumps(FULL)
    assert _parse_json(raw) == FULL  # valid JSON is returned verbatim
    salvaged = _parse_json(raw[: raw.rindex("}", 0, raw.rindex("}"))])  # drop the tail of the document
    assert salvaged["claims"] and "salvaged_truncated" in salvaged
    draft = _parse_draft(salvaged)  # `claim` / `text` keys both feed the normal draft parser
    assert draft.claims and all(c.source_ids for c in draft.claims) and draft.missing_evidence
    assert _parse_json("")["missing_evidence"] == ["Empty LLM response"]
    assert _parse_json("garbage")["missing_evidence"] == ["LLM returned invalid JSON"]


class _FakeClient:
    posts: list[dict] = []
    responses: list[str] = []

    def __init__(self, *a, **k): ...
    def __enter__(self): return self
    def __exit__(self, *a): return False

    def post(self, url, json):  # noqa: A002
        _FakeClient.posts.append(json)
        body = _FakeClient.responses.pop(0)
        return type("R", (), {"raise_for_status": lambda s: None, "json": lambda s: {"response": body}})()


def test_one_concise_retry_only_when_nothing_is_salvageable(monkeypatch):
    monkeypatch.setattr(llm_mod.httpx, "Client", _FakeClient)
    good = json.dumps({"claims": [{"text": "ok claim sentence here", "source_ids": ["a#s0"]}], "missing_evidence": []})
    _FakeClient.posts, _FakeClient.responses = [], ['{"claims": [{"text": "cut', good]
    out = OllamaLLMProvider().generate_json("PROMPT")
    assert out["claims"][0]["text"] == "ok claim sentence here" and len(_FakeClient.posts) == 2
    assert _FakeClient.posts[1]["prompt"] == "PROMPT" + CONCISE_RETRY_SUFFIX
    assert _FakeClient.posts[0]["options"]["num_predict"] == 1024 and _FakeClient.posts[0]["options"]["num_ctx"] == 4096
    assert _FakeClient.posts[0]["options"]["temperature"] == 0.0

    # salvageable truncation: NO retry
    trunc = '{"claims": [{"text": "ok claim sentence here", "source_ids": ["a#s0"]}, {"text": "dangling'
    _FakeClient.posts, _FakeClient.responses = [], [trunc]
    out = OllamaLLMProvider().generate_json("PROMPT")
    assert out["claims"] and len(_FakeClient.posts) == 1

    # still garbage after the retry -> honest invalid-JSON marker, never an invented claim
    _FakeClient.posts, _FakeClient.responses = [], ["x", "y"]
    out = OllamaLLMProvider().generate_json("PROMPT")
    assert out["claims"] == [] and len(_FakeClient.posts) == 2


def test_token_budget_and_concise_prompt_rule():
    assert settings.llm_max_tokens == 1024 and settings.llm_num_ctx == 4096 and settings.llm_temperature == 0.0
    assert "AT MOST 6-8 atomic claims" in build_claim_prompt("What is the penal charge?", [])


# ------------------------------------------------------------------ RBI circular ids + timeline extension
LETTERHEAD_DEC = """Caution: RBI never sends mails, SMSs or makes calls asking for personal information.
RBI/2023-24/102
DoR.MCS.REC.61/01.01.001/2023-24
December 29, 2023
Reference is invited to RBI circular DoR.MCS.REC.28/01.01.001/2023-24 dated August 18, 2023 on penal charges."""


def test_extract_reference_ids_takes_letterhead_ids_only():
    assert extract_reference_ids(LETTERHEAD_DEC) == ["RBI/2023-24/102", "DoR.MCS.REC.61/01.01.001/2023-24"]
    assert extract_reference_ids("RBI/2023-24/53 DoR.MCS.REC.28/01.01.001/2023-24 August 18, 2023") == \
        ["RBI/2023-24/53", "DoR.MCS.REC.28/01.01.001/2023-24"]
    assert extract_reference_ids("Circular No. DOR.STR.REC.45/2023-24 dated 01.04.2023") == ["DOR.STR.REC.45/2023-24"]
    assert extract_reference_ids("Body text says see DoR.MCS.REC.28/01.01.001/2023-24 for details of many things.") == []


def _chunk(doc, idx, page, sentences, section=None):
    cid = f"{doc}_p{page}_c{idx}"
    sents = [Sentence(sentence_id=f"{cid}#s{i}", chunk_id=cid, text=t, page=page) for i, t in enumerate(sentences)]
    return Chunk(chunk_id=cid, doc_id=doc, doc_name=f"{doc}.pdf", page=page, section=section, section_context=section or "",
                 text=" ".join(sentences), sentences=sents)


REF_HEAD = "Reference is invited to RBI circular DoR.MCS.REC.28/01.01.001/2023-24 dated August"


def _rbi_chunks():
    """Mirrors the real PDFs: the bold reference line is a heading (only visible as chunk.section) and RBI's
    line-wrapped text becomes sentence fragments."""
    return [
        _chunk("rec28", 1, 1, ["Fair Lending Practice - Penal Charges in Loan Accounts", "The instructions shall come into effect from January 1, 2024."]),
        _chunk("rec38", 1, 1, ["Responsible Lending Conduct - Release of Property Documents.", "The RE shall compensate the borrower at the rate of ₹5,000/- for each day of delay."]),
        _chunk("rec61", 1, 1, ["All Commercial Banks and All NBFCs", "Madam / Dear Sir,"]),
        _chunk("rec61", 2, 1, ["18, 2023 on ‘Fair Lending Practice - Penal Charges in Loan Accounts’.",
                               "2. In terms of paragraph 3 (viii) of the circular, the instructions were to come into effect",
                               "from January 1, 2024. However, considering that additional time has been sought,",
                               "it has been decided to extend the timeline for",
                               "implementation of the instructions by three months. Accordingly, REs shall ensure that",
                               "the instructions are implemented in respect of all the fresh loans availed from April 1,",
                               "2024 onwards."], section=REF_HEAD),
    ]


ALIASES = {"rec28": ["RBI/2023-24/53", "DoR.MCS.REC.28/01.01.001/2023-24"],
           "rec38": ["RBI/2023-24/60", "DoR.MCS.REC.38/01.01.001/2023-24"],
           "rec61": ["RBI/2023-24/102", "DoR.MCS.REC.61/01.01.001/2023-24"]}
NAMES = {d: f"{d}.pdf" for d in ALIASES}


def test_rbi_timeline_extension_creates_directed_amends_edge():
    chunks = _rbi_chunks()
    edges = extract_amendment_edges(chunks, NAMES, ALIASES)
    (e,) = edges  # REC.38 (property documents) is unrelated: no edge for it
    assert (e.from_doc_id, e.to_doc_id, e.relation) == ("rec61", "rec28", "AMENDS")
    assert e.effective_date == "2024-04-01" and e.evidence_page == 1
    assert e.evidence_quote == "it has been decided to extend the timeline for"  # a stored, verbatim sentence
    stored = {s.sentence_id: s.text for c in chunks for s in c.sentences}
    assert stored[e.evidence_sentence_id or ""] == e.evidence_quote
    (chain,) = build_amendment_chains(edges, NAMES)
    assert chain.doc_ids_ordered == ["rec28", "rec61"] and chain.active_doc_id == "rec61"


def test_regulatory_linking_needs_both_a_resolvable_reference_and_modification_phrasing():
    chunks = _rbi_chunks()
    assert extract_amendment_edges(chunks, NAMES) == []  # no aliases known -> the reference cannot be resolved
    wrong = {**ALIASES, "rec28": ["RBI/2020-21/1"]}
    assert extract_amendment_edges(chunks, NAMES, wrong) == []
    plain = _rbi_chunks()
    plain[3] = _chunk("rec61", 2, 1, ["2. REs shall publish the schedule of charges on their websites.",
                                      "Penal charges shall be reasonable."], section=REF_HEAD)
    assert extract_amendment_edges(plain, NAMES, ALIASES) == []  # reference but no modification phrasing
    other = _rbi_chunks()
    other[3] = _chunk("rec61", 2, 1, ["The timeline was extended by the Board of the RE."])  # modification, no reference
    assert extract_amendment_edges(other, NAMES, ALIASES) == []


def test_other_modification_triggers():
    for phrase in ("This circular modified the earlier instructions.", "Clause 5 stands amended as follows.",
                   "The words in clause 3 shall be substituted by the following."):
        ch = [_chunk("rec28", 1, 1, ["Original instructions apply."]),
              _chunk("rec61", 1, 1, ["Please refer to RBI circular DoR.MCS.REC.28/01.01.001/2023-24 dated August 18, 2023.", phrase])]
        (e,) = extract_amendment_edges(ch, NAMES, ALIASES)
        assert (e.from_doc_id, e.to_doc_id, e.relation) == ("rec61", "rec28", "AMENDS"), phrase


RBI_DIR = Path(__file__).resolve().parents[2] / "data" / "documents"
RBI_FILES = {k: next(iter(RBI_DIR.glob(f"{p}*.pdf")), None) for k, p in
             {"rec28": "FAIRLENDING", "rec38": "NOTI", "rec61": "PENALCHARGES"}.items()}


@pytest.mark.skipif(not all(RBI_FILES.values()), reason="real RBI PDFs not present")
def test_real_rbi_pdfs_link_rec61_amends_rec28(monkeypatch, tmp_path):
    from app.ingestion.service import ingest_pdf_file

    monkeypatch.setattr(settings, "data_dir", str(tmp_path))
    st = AppStore(workspace="byo_private")
    docs = {k: ingest_pdf_file(f, app_store=st) for k, f in RBI_FILES.items() if f}
    assert "DoR.MCS.REC.61/01.01.001/2023-24" in docs["rec61"].aliases
    assert "DoR.MCS.REC.28/01.01.001/2023-24" in docs["rec28"].aliases
    (e,) = st.amendment_edges
    assert (e.from_doc_id, e.to_doc_id, e.relation) == (docs["rec61"].doc_id, docs["rec28"].doc_id, "AMENDS")
    assert e.effective_date == "2024-04-01" and "extend the timeline" in e.evidence_quote
    assert st.get_sentence(e.evidence_sentence_id or "")["text"] == e.evidence_quote  # type: ignore[index]
