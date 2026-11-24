"""Workspace isolation + zero-guessing conversational layer (no model downloads: all providers are fakes)."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate

import app.core.store as store_mod
import app.main as main
from app.core.config import settings
from app.core.store import AppStore
from app.models.schemas import AskRequest, AskResponse, ChatTurn
from app.qa.followup import plan_turn, rewrite_followup
from app.qa.llm import FakeLLMProvider
from app.qa.service import ask_question
from app.retrieval.embeddings import FakeEmbeddingProvider
from app.retrieval.reranker import FakeRerankerProvider
from app.verification.nli import FakeNLIProvider
from tests.helpers import sample_store

LATE_Q = "What is the late payment fee according to the latest active rule?"
CALC_Q = "Calculate my late payment penalty under the latest active rule."


def _ask(st, question, history=None, llm=None, **kw):
    settings.rerank_abstain_threshold = 0.0
    llm = llm or FakeLLMProvider()
    resp = ask_question(question=question, app_store=st, embedding_provider=FakeEmbeddingProvider(),
                        reranker_provider=FakeRerankerProvider(), nli_provider=FakeNLIProvider(),
                        llm_provider=llm, history=history, **kw)
    return resp, llm


def _pdf(path, text):
    SimpleDocTemplate(str(path)).build([Paragraph(text, getSampleStyleSheet()["Normal"])])


@pytest.fixture
def api(monkeypatch, tmp_path):
    """TestClient with a sample-backed bank_official store, a fresh byo_private store and a tmp data dir."""
    bank = sample_store()
    byo = AppStore(workspace="byo_private")
    monkeypatch.setattr(main, "store", bank)
    monkeypatch.setitem(store_mod._stores, "byo_private", byo)
    monkeypatch.setattr(settings, "data_dir", str(tmp_path / "data"))
    monkeypatch.setattr(settings, "index_dir", str(tmp_path / "data" / "index"))
    monkeypatch.setattr(main, "rebuild_runtime_index", lambda *_a, **_k: None)  # no embedding model
    monkeypatch.setattr(main.settings, "enable_nli", False)
    monkeypatch.setattr(settings, "rerank_abstain_threshold", 0.0)
    return TestClient(main.app), bank, byo, tmp_path


# =============================================================== Feature 1: workspace isolation
def test_workspaces_are_isolated_for_ingest_delete_and_queries(api):
    c, bank, byo, tmp = api
    assert c.get("/api/documents").json()["summary"]["documents"] == 4  # default workspace is bank_official
    assert c.get("/api/documents?workspace=bank_official").json()["summary"]["documents"] == 4
    assert c.get("/api/documents?workspace=byo_private").json()["documents"] == []

    # a private upload with the SAME file name as an official policy
    pdf = tmp / "Acme_Loan_Policy_v3.pdf"
    _pdf(pdf, "The private sandbox says the cashback rate is 4% per quarter for gold members.")
    with open(pdf, "rb") as fh:
        r = c.post("/api/ingest?workspace=byo_private", files=[("files", ("Acme_Loan_Policy_v3.pdf", fh, "application/pdf"))])
    assert r.status_code == 200 and not r.json()["errors"] and r.json()["workspace"] == "byo_private"
    assert len(byo.documents) == 1 and len(bank.documents) == 4
    assert all("cashback" not in ch.text for ch in bank.chunks.values())  # nothing leaked into the bank corpus
    assert all("late payment" not in ch.text.lower() for ch in byo.chunks.values())  # nor the other way round
    (bdoc,) = byo.documents.values()
    assert "byo_private" in bdoc.file_path and bdoc.file_path != bank.documents["acme_loan_policy_v3"].file_path  # no PDF overwrite

    # queries only see their own workspace
    resp_bank, _ = _ask(bank, "What is the cashback rate for gold members?")
    assert not any("cashback" in cl.text.lower() for cl in resp_bank.claims)
    resp_byo, _ = _ask(byo, LATE_Q)
    assert resp_byo.workspace == "byo_private"
    assert not any("late payment" in cl.text.lower() or "2%" in cl.text for cl in resp_byo.claims)  # no bank policy text
    assert all(cit.doc_id in byo.documents and cit.doc_id + "_" in cit.chunk_id + "_" for cl in resp_byo.claims for cit in cl.citations)

    # contradictions are per-workspace
    assert c.get("/api/contradictions").json()["count"] == 2
    assert c.get("/api/contradictions?workspace=byo_private").json()["count"] == 0

    # rendering resolves documents only inside the requested workspace
    assert c.get("/api/documents/acme_loan_policy_v3/page/1/render").status_code == 200
    assert c.get("/api/documents/acme_loan_policy_v1/page/1/render?workspace=byo_private").status_code == 404

    # deleting in byo_private never touches bank_official
    assert c.delete(f"/api/documents/{bdoc.doc_id}?workspace=byo_private").status_code == 200
    assert not byo.documents and len(bank.documents) == 4
    assert c.delete("/api/documents/acme_loan_policy_v1?workspace=byo_private").status_code == 404
    assert len(bank.documents) == 4
    c.post("/api/ingest?workspace=byo_private", files=[("files", ("x.pdf", pdf.read_bytes(), "application/pdf"))])
    assert c.delete("/api/documents?workspace=byo_private").json()["deleted_documents"] == 1
    assert len(bank.documents) == 4 and len(bank.chunks) > 0 and len(bank.amendment_edges) == 2

    # ...and clearing bank_official leaves byo_private alone
    c.post("/api/ingest?workspace=byo_private", files=[("files", ("y.pdf", pdf.read_bytes(), "application/pdf"))])
    assert c.delete("/api/documents?workspace=bank_official").json()["deleted_documents"] == 4
    assert len(byo.documents) == 1 and not bank.documents


def test_unknown_workspace_is_rejected(api):
    c, *_ = api
    assert c.get("/api/documents?workspace=nope").status_code == 400
    assert c.post("/api/ask", json={"question": "hi", "workspace": "nope"}).status_code == 400
    assert c.get("/api/contradictions?workspace=../x").status_code == 400


def test_ingest_never_trusts_client_path_components(api):
    c, _, byo, tmp = api
    pdf = tmp / "s.pdf"
    _pdf(pdf, "A private note about nothing in particular.")
    c.post("/api/ingest?workspace=byo_private", files=[("files", ("../../evil.pdf", pdf.read_bytes(), "application/pdf"))])
    assert [d.doc_name for d in byo.documents.values()] == ["evil.pdf"]
    assert not (tmp / "evil.pdf").exists() and not (tmp.parent / "evil.pdf").exists()


def test_workspace_summary_endpoint(api):
    c, bank, _byo, _tmp = api
    data = c.get("/api/workspaces/summary").json()["workspaces"]
    assert set(data) == {"bank_official", "byo_private"}
    b = data["bank_official"]
    assert b["doc_count"] == 4 and b["chunk_count"] == len(bank.chunks) > 0
    assert b["amendment_chains_count"] == 1 and b["unresolved_contradictions_count"] == 2
    assert set(b["contradiction_subjects"]) == {"late payment fee", "grace period"}
    assert data["byo_private"] == {"doc_count": 0, "chunk_count": 0, "amendment_chains_count": 0,
                                   "unresolved_contradictions_count": 0, "contradiction_subjects": [], "doc_names": []}
    # summary reflects the workspace the moment its corpus changes
    c.delete("/api/documents/acme_operations_notice?workspace=bank_official")
    assert c.get("/api/workspaces/summary").json()["workspaces"]["bank_official"]["unresolved_contradictions_count"] == 0


def test_models_are_shared_singletons_across_workspaces():
    """Workspaces own only their data; the ML providers are process-wide singletons (no per-workspace model RAM)."""
    from app.retrieval.embeddings import SentenceTransformerEmbeddingProvider
    from app.retrieval.reranker import CrossEncoderRerankerProvider
    from app.verification.nli import HFNLIProvider

    for cls in (SentenceTransformerEmbeddingProvider, CrossEncoderRerankerProvider, HFNLIProvider):
        assert cls.get_instance() is cls.get_instance()
    for fld in AppStore.__dataclass_fields__:
        assert "model" not in fld and "provider" not in fld  # a store never holds a model
    assert store_mod.get_store("bank_official") is store_mod.store
    assert store_mod.get_store("byo_private") is not store_mod.store


def test_old_clients_stay_backwards_compatible():
    req = AskRequest(question="x")
    assert req.workspace == "bank_official" and req.history == []
    resp = AskResponse(request_id="r", question="q", status="abstained", answer="a")
    assert resp.rewritten_question is None and resp.clarification_needed is None


# ============================================ Feature 2a: calculation slot filling (zero guessing)
def test_calculation_missing_inputs_returns_clarification_and_never_guesses():
    st = sample_store()
    resp, _llm = _ask(st, CALC_Q)
    cl = resp.clarification_needed
    assert cl is not None and cl.kind == "calculation_inputs"
    assert [f.key for f in cl.missing_fields] == ["principal", "months"]
    assert [f.label for f in cl.missing_fields] == ["Overdue Amount (₹)", "Months Overdue"]
    assert "2%/month" in cl.message and cl.base_question == CALC_Q
    assert resp.calculation is None  # nothing computed from invented inputs
    assert "Rs" not in resp.answer.replace("Rs 1,000", "")  # no made-up amount in the answer
    assert resp.claims and all(c.status == "supported" for c in resp.claims)
    assert resp.question == CALC_Q and resp.rewritten_question is None
    assert any("2%" in c.text for c in resp.claims) and resp.faithfulness_pct == 100.0  # verified rate shown
    assert cl.pending_calculation["missing"] == ["principal", "months"]


def test_turn_two_fills_slots_and_computes_exact_decimal_result():
    st = sample_store()
    t1, _ = _ask(st, CALC_Q)
    hist = [ChatTurn(question=CALC_Q, answer_summary=t1.answer, pending_calculation=(t1.clarification_needed and t1.clarification_needed.pending_calculation))]
    for reply in ("50000 for 2 months", "Rs 50,000 for 2 months"):
        t2, _ = _ask(st, reply, history=hist)
        assert t2.calculation and t2.calculation.result == "Rs 2,000" and t2.calculation.result_value == 2000.0
        assert t2.rewritten_question == "Calculate the late payment penalty on Rs 50,000 for 2 months under the latest active rule."
        assert t2.clarification_needed is None and t2.question == reply
        assert t2.calculation.citation and "Acme_Loan_Policy_v3" in t2.calculation.citation.doc_name
        assert t2.faithfulness_pct == 100.0 and t2.claims


def test_calculation_followup_reuses_prior_principal_and_changes_the_period():
    st = sample_store()
    t1, _ = _ask(st, CALC_Q)
    hist1 = [ChatTurn(question=CALC_Q, answer_summary=t1.answer, pending_calculation=t1.clarification_needed.pending_calculation)]
    t2, _ = _ask(st, "Rs 50000 for 3 months", history=hist1)
    assert t2.calculation and t2.calculation.result == "Rs 3,000"
    hist2 = hist1 + [ChatTurn(question="Rs 50000 for 3 months",
                              answer_summary="A late payment fee of 2% per month applies after the grace period. "
                                             "Calculated (deterministic, from the cited active rule): Rs 3,000.")]
    for reply, expected in (("what about for 4 months?", "Rs 4,000"), ("what about Rs 60,000?", "Rs 3,600")):
        t3, _ = _ask(st, reply, history=hist2)
        assert t3.rewritten_question == (
            "Calculate the late payment penalty on Rs 50,000 for 4 months under the latest active rule." if "4 months" in reply
            else "Calculate the late payment penalty on Rs 60,000 for 3 months under the latest active rule."
        )
        assert t3.calculation and t3.calculation.result == expected
        assert t3.clarification_needed is None
    t3, _ = _ask(st, "what about for 4 months?", history=hist2)
    hist3 = hist2 + [ChatTurn(question="what about for 4 months?",
                              answer_summary="A late payment fee of 2% per month applies after the grace period. "
                                             "Calculated (deterministic, from the cited active rule): Rs 4,000.")]
    t4, _ = _ask(st, "what about for 25000 rs?", history=hist3)
    assert t4.rewritten_question == "Calculate the late payment penalty on Rs 25,000 for 4 months under the latest active rule."
    assert t4.calculation and t4.calculation.result == "Rs 2,000"
    t5, _ = _ask(st, "what about 25,000?", history=hist3)
    assert t5.rewritten_question == "Calculate the late payment penalty on Rs 25,000 for 4 months under the latest active rule."
    assert t5.calculation and t5.calculation.result == "Rs 2,000"
    t6, _ = _ask(st, "what about 4-months?", history=hist2)
    assert t6.rewritten_question == "Calculate the late payment penalty on Rs 50,000 for 4 months under the latest active rule."
    assert t6.calculation and t6.calculation.result == "Rs 4,000"


def test_repeated_calculation_followups_keep_their_inputs_beyond_two_turns():
    st = sample_store()
    q1 = "Calculate the late payment penalty on Rs 50,000 for 2 months under the latest active rule."
    t1, _ = _ask(st, q1)
    h1 = [ChatTurn(question=q1, answer_summary=t1.answer, calculation_kind=t1.calculation.kind,
                   calculation_inputs=t1.calculation.inputs)]
    t2, _ = _ask(st, "what about 4 months?", history=h1)
    h2 = h1 + [ChatTurn(question="what about 4 months?", answer_summary=t2.answer, calculation_kind=t2.calculation.kind,
                        calculation_inputs=t2.calculation.inputs)]
    t3, _ = _ask(st, "what about 25,000?", history=h2)
    assert t3.calculation and t3.calculation.result == "Rs 2,000"  # 25k at 2% for 4 months
    h3 = h2 + [ChatTurn(question="what about 25,000?", answer_summary=t3.answer, calculation_kind=t3.calculation.kind,
                        calculation_inputs=t3.calculation.inputs)]
    t4, _ = _ask(st, "what about 6 months?", history=h3)
    assert t4.rewritten_question == "Calculate the late payment penalty on Rs 25,000 for 6 months under the latest active rule."
    assert t4.calculation and t4.calculation.result == "Rs 3,000"


def test_partial_reply_asks_only_for_what_is_still_missing():
    st = sample_store()
    t1, _ = _ask(st, CALC_Q)
    hist = [ChatTurn(question=CALC_Q, pending_calculation=(t1.clarification_needed and t1.clarification_needed.pending_calculation))]
    t2, _ = _ask(st, "Rs 50,000", history=hist)
    cl = t2.clarification_needed
    assert cl is not None and [f.key for f in cl.missing_fields] == ["months"] and t2.calculation is None
    hist2 = [ChatTurn(question="Rs 50,000", pending_calculation=cl.pending_calculation)]
    t3, _ = _ask(st, "2", history=hist2)  # months now the only open slot, so a bare number is unambiguous
    assert t3.calculation and t3.calculation.result == "Rs 2,000"


def test_ambiguous_or_unrelated_replies_do_not_fill_slots():
    pend = {"kind": "late_fee", "missing": ["principal", "months"], "known": {}, "base_question": CALC_Q}
    hist = [ChatTurn(question=CALC_Q, pending_calculation=pend)]
    assert plan_turn("2", hist).pending is None and plan_turn("2", hist).pipeline_question == "2"  # lone number: never guess
    p = plan_turn("What is the grace period of 15 days?", hist)  # a new question, not a slot reply
    assert p.pipeline_question == "What is the grace period of 15 days?" and p.pending is None
    p = plan_turn("Calculate the late payment penalty on Rs 10,000 for 3 months", hist)  # full new request
    assert p.pending is None and p.rewritten_question is None
    # tampered pending state is ignored, not trusted
    bad = [ChatTurn(question="x", pending_calculation={"kind": "drop table", "missing": ["principal"], "known": {"principal": "abc"}})]
    assert plan_turn("Rs 50,000 for 2 months", bad).rewritten_question is None


def test_complete_calculation_request_is_untouched_and_factual_questions_are_not_calculations():
    st = sample_store()
    full = "Calculate the late payment penalty on an overdue EMI of Rs 50,000 for 2 months under the latest active rule."
    resp, _ = _ask(st, full)
    assert resp.clarification_needed is None and resp.rewritten_question is None
    assert resp.calculation and resp.calculation.result == "Rs 2,000"
    resp, _ = _ask(st, "How much is the late payment fee?")
    assert resp.clarification_needed is None  # a factual question never triggers the slot form


# ===================================================== Feature 2b: safe follow-up rewriting
HIST = [ChatTurn(question=LATE_Q, answer_summary="The late payment fee is 2% per month under Acme_Loan_Policy_v3.")]


def test_followup_rewrite_rules_and_standalone_questions_are_never_mutated():
    assert rewrite_followup("What about in v1?", HIST) == ("What is the late payment fee in v1?", "rule")
    assert rewrite_followup("and in v2?", HIST)[0] == "What is the late payment fee in v2?"
    assert rewrite_followup("Same for v1", HIST)[0] == "What is the late payment fee in v1?"
    assert rewrite_followup("What about the grace period?", HIST)[0] == "What is the grace period?"
    assert rewrite_followup("explain more", HIST)[0] == "Explain the late payment fee in more detail."
    for standalone in ("What is the late payment fee in v1?", "What is the grace period?",
                       "What is the policy on cryptocurrency collateral for personal loans?",
                       "Are there any conflicting rules on late payment fees or grace periods?"):
        assert rewrite_followup(standalone, HIST) == (None, "none"), standalone
    assert rewrite_followup("What about in v1?", []) == (None, "none")  # no history: nothing to resolve


def test_followup_flows_through_the_gates_as_the_rewritten_question():
    st = sample_store()
    resp, llm = _ask(st, "What about in v1?", history=HIST)
    assert resp.rewritten_question == "What is the late payment fee in v1?" and resp.question == "What about in v1?"
    assert "What is the late payment fee in v1?" in llm.calls[0]  # the drafting prompt got the standalone question
    assert "Acme_Loan_Policy_v3.pdf | page" not in llm.calls[0]  # retrieval is scoped to the named v1
    assert resp.pipeline_trace is not None and resp.pipeline_trace.gate1_retrieval.threshold == 0.0  # Gate 1 ran this turn
    assert resp.claims and all(cit.sentence_id in st.sentence_index for cl in resp.claims for cit in cl.citations)
    plain, _ = _ask(st, "What is the grace period?", history=HIST)
    assert plain.rewritten_question is None


def test_llm_rewriter_fallback_is_validated():
    ok = FakeLLMProvider(responses=[{"standalone_question": "What is the grace period for the late payment fee?"}])
    assert rewrite_followup("how long before it applies?", HIST, ok) == ("What is the grace period for the late payment fee?", "llm")
    smuggled = FakeLLMProvider(responses=[{"standalone_question": "What is the late payment fee of 2% in v1?"}])
    prior = [ChatTurn(question="What is the grace period?", answer_summary="It is 15 days.")]
    assert rewrite_followup("how about it in the old one?", prior, smuggled)[0] is None
    multi = FakeLLMProvider(responses=[{"standalone_question": "line one\nline two"}])
    assert rewrite_followup("and that?", HIST, multi)[0] is None
    assert rewrite_followup("and that?", HIST, FakeLLMProvider(responses=[{}]))[0] is None  # garbage -> no rewrite

    class Down:
        def generate_json(self, _prompt):
            raise RuntimeError("ollama down")

    assert rewrite_followup("and that?", HIST, Down())[0] is None  # LLM failure never invents a question


def test_only_last_two_turns_are_considered():
    old = ChatTurn(question="What is the grace period?", answer_summary="15 days")
    hist = [old, ChatTurn(question="Hello there", answer_summary="hi"), ChatTurn(question="Thanks", answer_summary="ok")]
    # the grace-period turn is 3 turns back -> out of scope; no single topic remains
    assert rewrite_followup("What about in v1?", hist)[0] is None


def test_chat_history_is_never_citable_evidence():
    st = sample_store()
    marker = "ZZ-HISTORY-MARKER a fee of 99.9% applies to platinum tier"
    hist = [ChatTurn(question=LATE_Q, answer_summary=marker)]
    llm = FakeLLMProvider(responses=[{"standalone_question": "What is the grace period for the late payment fee?"}])
    resp, llm = _ask(st, "how long before it applies?", history=hist, llm=llm)
    assert resp.rewritten_question == "What is the grace period for the late payment fee?"
    assert "ZZ-HISTORY-MARKER" in llm.calls[0]  # only the tiny rewriter may read history...
    assert all("ZZ-HISTORY-MARKER" not in p and "99.9%" not in p for p in llm.calls[1:])  # ...never the claim drafter
    blob = resp.model_dump_json()
    assert "ZZ-HISTORY-MARKER" not in blob.replace(resp.question, "") and "99.9%" not in blob
    for cl in resp.claims:
        for cit in cl.citations:
            assert (st.get_sentence(cit.sentence_id) or {}).get("text") == cit.quote  # every quote is a stored PDF sentence

    # an answer that exists ONLY in chat history is not provable -> the pipeline abstains instead of echoing it
    hist2 = [ChatTurn(question="What is the platinum tier fee?", answer_summary="The platinum tier fee is 99.9%.")]
    resp2, _ = _ask(st, "What is the platinum tier fee?", history=hist2)
    assert not any("99.9" in cl.text for cl in resp2.claims) and "99.9" not in resp2.answer
