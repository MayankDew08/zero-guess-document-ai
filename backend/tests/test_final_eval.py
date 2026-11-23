from __future__ import annotations

import pymupdf
from fastapi.testclient import TestClient
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate

import app.ingestion.service as ingestion_service
import app.main as main
from app.amendments.graph import extract_amendment_edges
from app.calculator.service import parse_amount
from app.contradictions.detector import typed_values
from app.core.config import settings
from app.ingestion.parser import locate_cells_bbox, parse_pdf
from app.models.schemas import Chunk, Sentence
from app.qa.llm import FakeLLMProvider
from app.qa.prompt import build_claim_prompt, is_hindi
from app.qa.service import ask_question
from app.qa.translate import render_claims_in_hindi
from app.reporting import render_html
from app.retrieval.embeddings import FakeEmbeddingProvider
from app.retrieval.reranker import FakeRerankerProvider
from app.verification.nli import FakeNLIProvider
from app.verification.numeric import check_numeric_date_match, extract_numbers
from tests.helpers import sample_store


# ---------------------------------------------------------------- Hindi -----------------------------
class StubNLI:
    """Language-aware stand-in for mDeBERTa (FakeNLIProvider is token-overlap only and cannot read Hindi).
    Hindi hypotheses: entailed iff all numbers match; English: entailed iff every hypothesis word is in the premise."""

    def predict(self, premise, hypothesis):
        import re

        nums = lambda t: set(re.findall(r"\d[\d,]*(?:\.\d+)?%?", t))  # noqa: E731
        if any("\u0900" <= ch <= "\u097f" for ch in hypothesis):
            ok = nums(hypothesis) == nums(premise) or nums(hypothesis) <= nums(premise)
        else:
            ok = set(hypothesis.lower().split()) <= set(premise.lower().split()) and nums(hypothesis) <= nums(premise)
        return {"entailment": 0.95, "neutral": 0.04, "contradiction": 0.01} if ok else {"entailment": 0.02, "neutral": 0.9, "contradiction": 0.08}


HI_Q = "नवीनतम सक्रिय नियम के अनुसार विलंब भुगतान शुल्क (late payment fee) क्या है?"


def test_hindi_detection_and_prompt_rules():
    assert is_hindi(HI_Q) and not is_hindi("What is the late payment fee?")
    p = build_claim_prompt(HI_Q, [])
    assert "natural Hindi (Devanagari script)" in p and "source_ids" in p
    assert "write claims in English" in build_claim_prompt("What is the late fee?", [])


def _ask(st, claims_responses, question, nli=None, **kw):
    settings.rerank_abstain_threshold = 0.0
    return ask_question(question=question, app_store=st, embedding_provider=FakeEmbeddingProvider(),
                        reranker_provider=FakeRerankerProvider(), nli_provider=nli or FakeNLIProvider(),
                        llm_provider=FakeLLMProvider(responses=claims_responses), **kw)


def _sid(st, needle):
    return next(s.sentence_id for c in st.all_chunks() for s in c.sentences if needle in s.text)


def test_hindi_rendering_is_verified_or_falls_back_to_english(monkeypatch):
    monkeypatch.setattr(settings, "rerank_abstain_threshold", 0.0)
    st = sample_store()
    sid = _sid(st, "2% per month applies on the overdue amount")
    draft = {"claims": [{"claim_id": "c1", "text": "A late payment fee of 2% per month applies on the overdue amount after the grace period.",
                         "claim_type": "numeric", "source_ids": [sid]}], "missing_evidence": []}
    good = {"translations": [{"claim_id": "c1", "hindi": "ग्रेस अवधि के बाद बकाया राशि पर प्रति माह 2% विलंब भुगतान शुल्क लगता है।"}]}
    back = {"translations": [{"claim_id": "c1", "english": "A late payment fee of 2% per month applies on the overdue amount after the grace period."}]}
    resp = _ask(st, [draft, good, back], HI_Q, nli=StubNLI())
    (c,) = resp.claims
    assert c.language == "hi" and c.text.startswith("ग्रेस") and c.text_en.startswith("A late payment fee of 2%")
    assert c.status == "supported" and resp.faithfulness_pct == 100.0
    assert "hindi_roundtrip_ok=True" in (c.citations[0].verification_notes or "")
    assert any("ऀ" <= ch <= "ॿ" for ch in resp.answer)  # Hindi lead-in

    # wrong number, stray Latin letters or foreign script -> rendering rejected, English shown
    for bad in ("ग्रेस अवधि के बाद प्रति माह 5% विलंब शुल्क लगता है।", "गrace अवधि के बाद प्रति माह 2% शुल्क।",
                "शुल्क का चารण प्रति माह 2% लगता है।"):
        resp = _ask(st, [draft, {"translations": [{"claim_id": "c1", "hindi": bad}]}, back], HI_Q, nli=StubNLI())
        (c,) = resp.claims
        assert c.language == "en" and c.text.startswith("A late payment fee of 2%") and c.status == "supported"


def test_hindi_roundtrip_rejects_a_mistranslation():
    st = sample_store()
    sid = _sid(st, "2% per month applies on the overdue amount")
    from app.models.schemas import Citation, Claim

    quote = st.get_sentence(sid)["text"]
    cl = Claim(claim_id="c1", text="A late payment fee of 2% per month applies after the grace period.", status="supported",
               source_ids=[sid], citations=[Citation(sentence_id=sid, chunk_id="x", doc_id="d", doc_name="D", page=1, quote=quote)])
    llm = FakeLLMProvider(responses=[
        {"translations": [{"claim_id": "c1", "hindi": "ग्रेस अवधि के बाद प्रति माह 2% धोखा शुल्क लगता है।"}]},
        {"translations": [{"claim_id": "c1", "english": "A fraud fee of 2% per month applies after the grace period."}]}])
    notes = render_claims_in_hindi([cl], llm, StubNLI())
    assert cl.language == "en" and cl.text_en is None and any("round-trip" in n for n in notes)


# ---------------------------------------------------------- table bbox --------------------------------
def test_table_row_bbox_is_the_union_of_cell_hits():
    st = sample_store()
    row = next(s for c in st.all_chunks() if c.chunk_type == "table" for s in c.sentences if s.text.startswith("Processing Fee"))
    pdf = pymupdf.open(st.documents["acme_loan_policy_v3"].file_path)
    page = pdf[0]
    box = locate_cells_bbox(page, row.text.split(" | "), hint=(row.bbox.x0, row.bbox.y0, row.bbox.x1, row.bbox.y1))
    assert box is not None
    hit_a = page.search_for("Processing Fee")[0]
    hit_b = page.search_for("INR 1,000")[0]
    assert box.x0 <= hit_a.x0 + 0.5 and box.x1 >= hit_b.x1 - 0.5 and abs(box.y0 - hit_a.y0) < 3
    assert box.height < 25  # one row, not the table
    assert row.bbox.y1 - row.bbox.y0 < 25 and abs(row.bbox.y0 - box.y0) < 4  # parser stored the tight row box


def test_pipe_joined_text_outside_a_table_is_located_by_cell_search(tmp_path):
    path = tmp_path / "pipes.pdf"
    ss = getSampleStyleSheet()
    SimpleDocTemplate(str(path), pagesize=LETTER).build([
        Paragraph("Fee schedule overview for retail loans.", ss["Normal"]),
        Paragraph("Processing Fee | INR 1,000 | At disbursement", ss["Normal"])])
    (page,) = parse_pdf(path)
    blk = next(b for b in page["blocks"] if "Processing Fee" in b["text"])
    bb = blk["sent_bboxes"]["Processing Fee | INR 1,000 | At disbursement"]
    assert bb.y1 - bb.y0 < 25 and bb.x1 > bb.x0


def test_render_highlights_table_row(monkeypatch):
    st = sample_store()
    monkeypatch.setattr(main, "store", st)
    from urllib.parse import quote

    sid = _sid(st, "Processing Fee | INR 1,000")
    c = TestClient(main.app)
    plain = c.get("/api/documents/acme_loan_policy_v3/page/1/render")
    hl = c.get(f"/api/documents/acme_loan_policy_v3/page/1/render?sentence_id={quote(sid)}")
    assert hl.status_code == 200 and hl.headers["content-type"] == "image/png" and hl.content != plain.content


# ------------------------------------------------------- delete / clear ------------------------------
def test_delete_document_and_clear_corpus(monkeypatch):
    st = sample_store()
    monkeypatch.setattr(main, "store", st)
    monkeypatch.setattr(ingestion_service, "store", st)
    monkeypatch.setattr(main, "rebuild_runtime_index", lambda *a, **k: None)
    monkeypatch.setattr(st, "save", lambda *a, **k: None)
    c = TestClient(main.app)
    n_before = len(st.chunks)
    assert len(st.amendment_edges) == 2

    r = c.delete("/api/documents/acme_loan_policy_v3")
    assert r.status_code == 200 and r.json()["deleted"] == "acme_loan_policy_v3"
    assert "acme_loan_policy_v3" not in st.documents
    assert all(ch.doc_id != "acme_loan_policy_v3" for ch in st.chunks.values()) and len(st.chunks) < n_before
    assert all(not sid.startswith("acme_loan_policy_v3") for sid in st.sentence_index)
    assert [e.relation for e in st.amendment_edges] == ["SUPERSEDES"]  # v2 -> v1 only; v3 edge gone
    assert c.delete("/api/documents/acme_loan_policy_v3").status_code == 404
    assert c.get("/api/documents").json()["summary"]["documents"] == 3

    r = c.delete("/api/documents")
    assert r.status_code == 200 and r.json()["deleted_documents"] == 3
    assert not st.documents and not st.chunks and not st.amendment_edges and not st.sentence_index
    assert c.get("/api/documents").json()["summary"]["chunks"] == 0


# ---------------------------------------------------- Indian regulatory text ------------------------
def _chunk(doc_id, name, sentences):
    cid = f"{doc_id}_p1_c1"
    sents = [Sentence(sentence_id=f"{cid}#s{i}", chunk_id=cid, text=t, page=1) for i, t in enumerate(sentences)]
    return Chunk(chunk_id=cid, doc_id=doc_id, doc_name=name, page=1, text=" ".join(sentences), sentences=sents)


def test_regulatory_phrasing_creates_directed_edges_with_dates():
    old = _chunk("rbi_cc_2023", "RBI_Credit_Card_Circular_2023.pdf",
                 ["Circular No. DOR.STR.REC.45/2023-24 dated 01.04.2023", "Interest on credit card dues shall not exceed 3.5% per month."])
    new = _chunk("rbi_cc_2024", "RBI_Credit_Card_Circular_2024.pdf",
                 ["Circular No. DOR.STR.REC.77/2024-25", "In partial modification of Circular No. DOR.STR.REC.45/2023-24, clause 5 is hereby amended to read as follows w.e.f. 01.04.2024.",
                  "The late payment charge shall not exceed Rs. 1,00,000."])
    names = {"rbi_cc_2023": old.doc_name, "rbi_cc_2024": new.doc_name}
    (e,) = extract_amendment_edges([old, new], names)
    assert (e.from_doc_id, e.to_doc_id, e.relation) == ("rbi_cc_2024", "rbi_cc_2023", "AMENDS")
    assert e.effective_date == "2024-04-01" and "partial modification" in e.evidence_quote

    mdir = _chunk("md_kyc", "Master_Direction_KYC_2016.pdf", ["Master Direction - Know Your Customer (KYC) Direction, 2016"])
    amend = _chunk("kyc_upd", "KYC_Update.pdf", ["This notification replaces clause 38 of the Master Direction - Know Your Customer (KYC) Direction, 2016 with effect from 1 June 2025."])
    (e2,) = extract_amendment_edges([mdir, amend], {"md_kyc": mdir.doc_name, "kyc_upd": amend.doc_name})
    assert (e2.from_doc_id, e2.to_doc_id, e2.relation) == ("kyc_upd", "md_kyc", "REPLACES") and e2.effective_date == "2025-06-01"


def test_indian_currency_formats():
    assert extract_numbers("₹ 1,00,000") == ["inr100000"] == extract_numbers("Rs. 1 lakh") == extract_numbers("INR 1,00,000")
    assert extract_numbers("Rs. 2.5 crore") == ["inr25000000"]
    assert extract_numbers("INR 50,000 and 2%") == ["inr50000", "2%"]
    assert check_numeric_date_match("The limit is Rs 1 lakh.", "The limit is ₹ 1,00,000 per customer.") == (True, None)
    assert not check_numeric_date_match("The limit is Rs 2 lakh.", "The limit is ₹ 1,00,000 per customer.")[0]
    assert parse_amount("fee on Rs. 1,00,000 overdue") == 100000
    assert parse_amount("fee on ₹5 lakh overdue") == 500000
    assert typed_values("charge of ₹ 1,00,000 or Rs. 2 lakhs") == [("currency", 100000.0, "₹ 1,00,000"), ("currency", 200000.0, "Rs. 2 lakhs")]


# ----------------------------------------------------- report + trace --------------------------------
def _conflict_response(monkeypatch):
    monkeypatch.setattr(settings, "rerank_abstain_threshold", 0.0)
    st = sample_store()
    s_v3, s_ops = _sid(st, "2% per month applies on the overdue amount"), _sid(st, "late payment fee of 5% per month")
    claims = [{"claim_id": "c1", "text": "A late payment fee of 2% per month applies on the overdue amount after the grace period.", "claim_type": "numeric", "source_ids": [s_v3]},
              {"claim_id": "c2", "text": "A late payment fee of 5% per month applies after the due date for all delinquent personal loan accounts.", "claim_type": "numeric", "source_ids": [s_ops]},
              {"claim_id": "c3", "text": "A late payment fee of 9% per month applies.", "claim_type": "numeric", "source_ids": [s_v3]}]
    return st, _ask(st, [{"claims": claims, "missing_evidence": ["international SWIFT wire transfer fee"]}], "What is the late payment fee?", debug=False)


def test_html_report_has_verbatim_quotes_side_by_side_and_edges(monkeypatch):
    st, resp = _conflict_response(monkeypatch)
    html = render_html(resp)
    for needle in ("A late payment fee of 2% per month applies on the overdue amount after the grace period.",
                   "Effective immediately, a late payment fee of 5% per month applies after the due date"):
        assert html.count(needle) >= 2  # claim quote + contradiction table
    assert "Contradiction Alerts" in html and "<th>Quote A</th><th>Quote B</th>" in html
    assert "Acme_Loan_Policy_v3.pdf" in html and "Acme_Operations_Notice.pdf" in html
    assert "This policy supersedes Acme Loan Policy v2 with effect from 1 January 2025." in html
    assert "SUPERSEDES" in html and "2025-01-01" in html and "Timeline (oldest" in html
    assert "Blocked / Rejected Claims" in html and "A late payment fee of 9% per month applies." in html
    assert "international SWIFT wire transfer fee" in html
    assert "Verification Pipeline Trace" in html and "CRAG retrieval" in html
    for m in (settings.ollama_model, settings.embedding_model, settings.reranker_model, settings.nli_model):
        assert m in html
    assert "OFFLINE" in html or "online model hub" in html
    clean = render_html(_ask(st, [{"claims": [], "missing_evidence": []}], "What is the late payment fee?"))
    assert "None — all drafted claims passed" not in clean or "Blocked claims" in clean


def test_report_endpoint_serves_the_html(monkeypatch, tmp_path):
    _, resp = _conflict_response(monkeypatch)
    monkeypatch.setattr(main.settings, "report_dir", str(tmp_path))
    c = TestClient(main.app)
    r = c.post("/api/report", json={"response": resp.model_dump(), "format": "html"})
    assert r.status_code == 200
    body = c.get(r.json()["download_url"]).text
    assert "Verified Claims" in body and "A late payment fee of 2% per month" in body


def test_pipeline_trace_schema_and_counts(monkeypatch):
    _, resp = _conflict_response(monkeypatch)
    t = resp.pipeline_trace.model_dump()
    assert set(t) == {"gate1_retrieval", "gate2_citation_resolution", "gate3_nli_and_numeric", "gate4_lineage_and_conflicts"}
    assert set(t["gate1_retrieval"]) == {"hybrid_candidates", "reranked_kept", "max_rerank_score", "threshold", "passed"}
    assert set(t["gate2_citation_resolution"]) == {"drafted_claims", "resolved_citations", "rejected_invalid_ids"}
    assert set(t["gate3_nli_and_numeric"]) == {"nli_passed", "nli_failed", "numeric_passed", "numeric_failed"}
    assert {"amendment_chains_found", "superseded_docs_filtered", "unresolved_contradictions"} <= set(t["gate4_lineage_and_conflicts"])
    assert t["gate1_retrieval"]["passed"] and t["gate1_retrieval"]["hybrid_candidates"] >= t["gate1_retrieval"]["reranked_kept"] > 0
    assert t["gate2_citation_resolution"] == {"drafted_claims": 3, "resolved_citations": 3, "rejected_invalid_ids": 0}
    assert t["gate3_nli_and_numeric"]["numeric_failed"] >= 1 and t["gate3_nli_and_numeric"]["numeric_passed"] == 2
    assert t["gate4_lineage_and_conflicts"]["superseded_docs_filtered"] == 2
    assert t["gate4_lineage_and_conflicts"]["unresolved_contradictions"] == 1
    body = TestClient(main.app)  # /api/ask exposes it even with debug=false
    assert body is not None


def test_no_evidence_statement_becomes_missing_evidence_not_a_blocked_claim(monkeypatch):
    monkeypatch.setattr(settings, "rerank_abstain_threshold", 0.0)
    st = sample_store()
    sid = _sid(st, "2% per month applies on the overdue amount")
    resp = _ask(st, [{"claims": [
        {"claim_id": "c1", "text": "A late payment fee of 2% per month applies after the grace period.", "claim_type": "numeric", "source_ids": [sid]},
        {"claim_id": "c2", "text": "No evidence found for the international SWIFT wire transfer fee.", "claim_type": "other", "source_ids": []}],
        "missing_evidence": []}], "What is the late payment fee and the international SWIFT wire transfer fee?")
    assert resp.blocked_claims_count == 0 and [c.claim_id for c in resp.claims] == ["c1"]
    assert any("SWIFT" in m for m in resp.missing_evidence) and not any("no_source_ids" in m for m in resp.missing_evidence)
