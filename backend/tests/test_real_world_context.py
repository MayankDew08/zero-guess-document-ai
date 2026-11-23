from __future__ import annotations

import pymupdf
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate

from app.amendments.graph import extract_amendment_edges
from app.core.config import settings
from app.core.store import AppStore
from app.ingestion.chunker import chunk_pages
from app.ingestion.parser import parse_pdf
from app.models.schemas import Document, DraftClaim
from app.qa.llm import FakeLLMProvider
from app.qa.service import ask_question
from app.retrieval.embeddings import FakeEmbeddingProvider
from app.retrieval.reranker import FakeRerankerProvider
from app.retrieval.service import retrieve
from app.verification.nli import FakeNLIProvider
from app.verification.numeric import check_numeric_date_match, extract_numbers
from app.verification.pipeline import resolve_and_verify_claims

ss = getSampleStyleSheet()
H1, H2, N = ss["Heading1"], ss["Heading2"], ss["Normal"]

BONUS_01 = "• Make and model recognition. • Tracking the same vehicle across two cameras."
BONUS_02 = "• Highlight the cited passage on a rendered view of the PDF page. • Support questions in Hindi."


def build_pdf(path):
    story = [
        Paragraph("AIML · AIML-01 · OPTION A", H1), Paragraph("Vehicle Identification from CCTV Footage", H1),
        Paragraph("Turn blurry footage into a ranked list of candidate vehicles.", N),
        Paragraph("Background", H2), Paragraph("Many road offences are captured only on blurred CCTV frames.", N),
        Paragraph("Bonus features", H2), Paragraph(BONUS_01, N),
        Paragraph("Deliverables", H2), Paragraph("• The working application. • A matching algorithm write-up.", N),
        PageBreak(),
        Paragraph("AIML · AIML-02 · OPTION B", H1), Paragraph("Zero-Guessing Document AI", H1),
        Paragraph("A document assistant that answers only with proof.", N),
        Paragraph("Background", H2), Paragraph("Banking teams need answers that can be proven from policy documents.", N),
        Paragraph("Bonus features", H2), Paragraph(BONUS_02, N),
        PageBreak(),
        Paragraph("Eligibility", H2), Paragraph("Teams of 2 to 4 members may participate in the hackathon.", N),
    ]
    SimpleDocTemplate(str(path), pagesize=LETTER).build(story)
    return path


def make_store(tmp_path) -> AppStore:
    pdf = build_pdf(tmp_path / "Problem_Statement.pdf")
    pages = parse_pdf(pdf)
    chunks = chunk_pages("ps", "Problem_Statement.pdf", pages)
    st = AppStore()
    st.add_document(Document(doc_id="ps", doc_name="Problem_Statement.pdf", file_path=str(pdf), num_pages=len(pages),
                             ingested_at="t", chunks_created=len(chunks)), chunks)
    st.amendment_edges = extract_amendment_edges(chunks, {"ps": "Problem_Statement.pdf"})
    return st


def test_section_context_comes_from_page_topic_and_subheading_without_touching_text(tmp_path):
    st = make_store(tmp_path)
    page_text = {i + 1: pg.get_text().replace("\n", " ") for i, pg in enumerate(pymupdf.open(tmp_path / "Problem_Statement.pdf"))}
    bonus = {c.page: c for c in st.all_chunks() if c.section == "Bonus features"}
    assert bonus[1].section_context == "AIML · AIML-01 · OPTION A — Vehicle Identification from CCTV Footage > Bonus features"
    assert bonus[2].section_context == "AIML · AIML-02 · OPTION B — Zero-Guessing Document AI > Bonus features"
    assert bonus[2].page_topic == "AIML · AIML-02 · OPTION B — Zero-Guessing Document AI"
    for c in st.all_chunks():  # verbatim: no context leaked into text / sentences
        assert "AIML-0" not in c.text or c.text in " ".join(page_text.values()) or "AIML" not in c.text
        for s in c.sentences:
            assert "Bonus features >" not in s.text and ">" not in s.text.replace("→", "")
            assert " ".join(s.text.split()) in " ".join(page_text[c.page].split())
    # page 3 has no new top-level heading: the AIML-02 topic is carried forward onto it
    elig = next(c for c in st.all_chunks() if c.section == "Eligibility")
    assert elig.page == 3 and elig.section_context.startswith("AIML · AIML-02 · OPTION B") and elig.section_context.endswith("> Eligibility")


def test_retrieval_text_is_contextual_but_text_stays_pure(tmp_path):
    st = make_store(tmp_path)
    c = next(c for c in st.all_chunks() if c.section == "Bonus features" and c.page == 2)
    rt = c.retrieval_text()
    assert rt.startswith("[Problem_Statement.pdf | p.2 | AIML · AIML-02 · OPTION B") and rt.endswith(c.text)
    assert "AIML-02" not in c.text and "Problem_Statement" not in c.text


def test_identically_named_sections_are_disambiguated(tmp_path, monkeypatch):
    st = make_store(tmp_path)
    monkeypatch.setattr(settings, "rerank_abstain_threshold", 0.0)
    res = retrieve("bonus features for AIML-02", app_store=st, embedding_provider=FakeEmbeddingProvider(),
                   reranker_provider=FakeRerankerProvider())
    top = res.chunks[0].chunk
    assert top.section == "Bonus features" and "AIML-02" in top.section_context and top.page == 2
    res1 = retrieve("bonus features for AIML-01", app_store=st, embedding_provider=FakeEmbeddingProvider(),
                    reranker_provider=FakeRerankerProvider())
    assert "AIML-01" in res1.chunks[0].chunk.section_context and res1.chunks[0].chunk.page == 1


def _sid(st, needle):
    return next(s.sentence_id for c in st.all_chunks() for s in c.sentences if needle in s.text)


def test_wrong_section_attribution_is_blocked_right_one_passes(tmp_path):
    st = make_store(tmp_path)
    nli = FakeNLIProvider()
    right = _sid(st, "Highlight the cited passage")
    wrong = _sid(st, "Make and model recognition")
    ok_claim = DraftClaim(claim_id="c1", text="For AIML-02, a bonus feature is to highlight the cited passage on a rendered view of the PDF page.", source_ids=[right])
    bad_claim = DraftClaim(claim_id="c2", text="For AIML-02, a bonus feature is make and model recognition.", source_ids=[wrong])
    shown, blocked = resolve_and_verify_claims([ok_claim, bad_claim], st, nli)
    assert [c.claim_id for c in shown] == ["c1"]
    assert [c.claim_id for c in blocked] == ["c2"] and "identifier" in blocked[0].reason
    cit = shown[0].citations[0]
    assert cit.section_context.endswith("> Bonus features") and "AIML-02" in cit.section_context
    assert "AIML" not in cit.quote  # the displayed quote stays pure


def test_nli_premise_carries_section_context(tmp_path):
    st = make_store(tmp_path)
    seen = []

    class Spy:
        def predict(self, premise, hypothesis):
            seen.append(premise)
            return {"entailment": 0.9, "neutral": 0.05, "contradiction": 0.05}

    sid = _sid(st, "Highlight the cited passage")
    resolve_and_verify_claims([DraftClaim(claim_id="c1", text="Highlight the cited passage on a rendered view.", source_ids=[sid])], st, Spy())
    assert seen and seen[0].startswith("AIML · AIML-02 · OPTION B") and "> Bonus features: Highlight the cited passage" in seen[0]


def test_identifier_codes_are_not_quantities():
    txt = "AIML-02 CS-01 W3-01 OI-01 GT-02 v3 RBI/2023-24/28 Section 4.2 Clause 3.1 Page 6 p.5"
    assert extract_numbers(txt) == []
    assert extract_numbers("AIML-02 allows 700 points, a 2% fee, INR 1,000 and 15 days") == ["700", "2%", "inr1000", "15"]
    ok, why = check_numeric_date_match("For AIML-02 the fee is 2%.", "The fee is 2%.", "AIML · AIML-02 · OPTION B > Fees")
    assert ok and why is None
    ok, why = check_numeric_date_match("Per RBI/2023-24/28 the limit is 60 days.", "The limit is 60 days.", "Circular RBI/2023-24/28")
    assert ok
    ok, why = check_numeric_date_match("CS-01 applies on page 6, clause 3.1 and Section 4.2.", "It applies.", "CYBERSECURITY · CS-01")
    assert ok


def test_real_quantity_mismatch_still_blocks_and_wrong_code_blocks():
    assert not check_numeric_date_match("The fee is 3%.", "The fee is 2%.", "AIML-02")[0]
    assert not check_numeric_date_match("AIML-02 fee is 2%.", "The fee is 2%.", "AIML · AIML-01")[0]
    assert not check_numeric_date_match("Minimum score is 650.", "Minimum score is 700.")[0]
    assert not check_numeric_date_match("Pay INR 2,000.", "Pay INR 1,000.")[0]
    assert not check_numeric_date_match("Grace period is 5 days.", "Grace period is 15 days.")[0]


def _ask(st, claims, missing=None):
    settings.rerank_abstain_threshold = 0.0
    return ask_question(question="What are the bonus features for AIML-02 and what is the 1st place prize money?", app_store=st,
                        embedding_provider=FakeEmbeddingProvider(), reranker_provider=FakeRerankerProvider(),
                        nli_provider=FakeNLIProvider(),
                        llm_provider=FakeLLMProvider(responses=[{"claims": claims, "missing_evidence": missing or []},
                                                                {"claims": [], "missing_evidence": []}]))  # 2nd call = prize part


def test_absence_statements_route_to_missing_evidence_but_affirmative_sourceless_claims_block(tmp_path):
    st = make_store(tmp_path)
    sid = _sid(st, "Highlight the cited passage")
    good = {"claim_id": "c1", "text": "For AIML-02, a bonus feature is to highlight the cited passage on a rendered view of the PDF page.", "claim_type": "factual", "source_ids": [sid]}
    for phrase in ("There is no specific 1st place prize money mentioned in the evidence.", "The 1st place prize is not mentioned.",
                   "The document does not state the first prize amount.", "No proof was found for the 1st place prize money.",
                   "The prize amount is not specified.", "1st place prize details are not provided."):
        resp = _ask(st, [good, {"claim_id": "c2", "text": phrase, "claim_type": "other", "source_ids": []}])
        assert resp.blocked_claims_count == 0, phrase
        assert phrase in resp.missing_evidence and not any("no_source_ids" in m for m in resp.missing_evidence)
        assert [c.claim_id for c in resp.claims] == ["c1"] and resp.faithfulness_pct == 100.0

    resp = _ask(st, [good, {"claim_id": "c3", "text": "The 1st place prize money is INR 50,000.", "claim_type": "numeric", "source_ids": []}])
    assert resp.blocked_claims_count == 1 and resp.blocked_claims[0].reason == "no_source_ids"
    assert "50,000" not in resp.answer


def test_all_blocked_reports_draft_support_zero(tmp_path):
    st = make_store(tmp_path)
    resp = _ask(st, [{"claim_id": "c1", "text": "The 1st place prize money is INR 50,000.", "claim_type": "numeric", "source_ids": []},
                     {"claim_id": "c2", "text": "The 2nd place prize is INR 20,000.", "claim_type": "numeric", "source_ids": []}])
    assert resp.status == "abstained" and resp.drafted_claims_count == 2 and resp.blocked_claims_count == 2
    assert resp.draft_support_pct == 0.0


def test_citation_snapping_repoints_an_off_by_one_id_but_not_a_good_one(tmp_path):
    from app.qa.service import snap_citations

    st = make_store(tmp_path)
    chunks = st.all_chunks()
    a, b = _sid(st, "Highlight the cited passage"), _sid(st, "Support questions in Hindi")
    off = DraftClaim(claim_id="c1", text="Support questions in Hindi.", source_ids=[a])  # cites the neighbouring sentence
    good = DraftClaim(claim_id="c2", text="Highlight the cited passage on a rendered view of the PDF page.", source_ids=[a])
    unrelated = DraftClaim(claim_id="c3", text="The 1st place prize is INR 50,000.", source_ids=[a])
    log = snap_citations([off, good, unrelated], chunks)
    assert off.source_ids == [b] and good.source_ids == [a] and unrelated.source_ids == [a]  # fabricated claim is NOT rescued
    assert log == [{"claim_id": "c1", "from": [a], "to": b, "similarity": 1.0}]
    shown, blocked = resolve_and_verify_claims([off, unrelated], st, FakeNLIProvider())
    assert [c.claim_id for c in shown] == ["c1"] and [c.claim_id for c in blocked] == ["c3"]


def test_question_decomposition_is_conservative():
    from app.qa.decompose import split_question_parts as sp

    assert sp("What are the bonus features for AIML-02 and what is the 1st place prize money?") == [
        "What are the bonus features for AIML-02?", "what is the 1st place prize money?"]
    assert len(sp("What is the late payment fee and what is the international SWIFT wire transfer fee?")) == 2
    assert len(sp("AIML-02 की बोनस सुविधाएँ (bonus features) क्या हैं और प्रथम स्थान की पुरस्कार राशि कितनी है?")) == 2
    for single in ("What are the processing fees, bounce charges, and borrower eligibility conditions?",
                   "Are there any conflicting rules on late payment fees or grace periods?",
                   "Calculate the penalty on Rs 50,000 and show the working."):
        assert sp(single) == [single]


def test_unproven_part_is_flagged_without_an_llm_call_for_it(tmp_path, monkeypatch):
    st = make_store(tmp_path)

    class OnlyPrizeFails(FakeRerankerProvider):
        def rerank(self, query, texts):
            return [0.0 for _ in texts] if "prize" in query.lower() else super().rerank(query, texts)

    llm = FakeLLMProvider(responses=[{"claims": [], "missing_evidence": []}])
    monkeypatch.setattr(settings, "rerank_abstain_threshold", 0.2)
    resp = ask_question(question="What are the bonus features for AIML-02 and what is the 1st place prize money?", app_store=st,
                        embedding_provider=FakeEmbeddingProvider(), reranker_provider=OnlyPrizeFails(),
                        nli_provider=FakeNLIProvider(), llm_provider=llm)
    assert len(llm.calls) == 1  # prize part was gated out before generation
    assert any("1st place prize money" in m for m in resp.missing_evidence)
