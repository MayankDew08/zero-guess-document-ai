"""Current-rule drafting: superseded-document awareness + oversized table-cell filter."""
from __future__ import annotations

from app.core.config import settings
from app.models.schemas import Chunk, RetrievedChunk, Sentence
from app.qa.llm import FakeLLMProvider
from app.qa.prompt import MAX_TABLE_ROW_CHARS, build_claim_prompt
from app.qa.service import ask_question, superseded_for_current_rule
from app.retrieval.embeddings import FakeEmbeddingProvider
from app.retrieval.reranker import FakeRerankerProvider
from app.verification.nli import FakeNLIProvider
from tests.helpers import sample_store

CURRENT_Q = "What is the late payment fee according to the latest active rule?"


def _sentence(st, doc_id, needle):
    return next(s for c in st.all_chunks() if c.doc_id == doc_id for s in c.sentences if needle in s.text)


def _ask(st, question, responses):
    settings.rerank_abstain_threshold = 0.0
    llm = FakeLLMProvider(responses=responses)
    resp = ask_question(question=question, app_store=st, embedding_provider=FakeEmbeddingProvider(),
                        reranker_provider=FakeRerankerProvider(), nli_provider=FakeNLIProvider(), llm_provider=llm)
    return resp, llm


def _claim(cid, sent):
    return {"claim_id": cid, "text": sent.text, "claim_type": "numeric", "source_ids": [sent.sentence_id]}


def test_current_rule_question_tags_superseded_docs_and_drops_superseded_only_claims():
    st = sample_store()
    old = _sentence(st, "acme_loan_policy_v1", "late payment")
    new = _sentence(st, "acme_loan_policy_v3", "2% per month")
    resp, llm = _ask(st, CURRENT_Q, [{"claims": [_claim("c1", old), _claim("c2", new)], "missing_evidence": []}])
    prompt = llm.calls[0]
    assert "[SUPERSEDED BY Acme_Loan_Policy_v3.pdf — DO NOT CITE AS CURRENT RULE]" in prompt
    assert prompt.index("Acme_Loan_Policy_v3.pdf | page") < prompt.index("Acme_Loan_Policy_v1.pdf | page")  # active evidence first
    assert [c.citations[0].doc_id for c in resp.claims] == ["acme_loan_policy_v3"]
    (b,) = [c for c in resp.blocked_claims if c.citations[0].doc_id == "acme_loan_policy_v1"]
    assert b.status == "blocked" and "superseded_document_not_current_rule" in (b.reason or "")
    assert resp.faithfulness_pct == 100.0 and old.text not in resp.answer


def test_superseded_only_answer_triggers_the_repair_round_with_the_active_document():
    st = sample_store()
    old = _sentence(st, "acme_loan_policy_v1", "late payment")
    new = _sentence(st, "acme_loan_policy_v3", "2% per month")
    resp, llm = _ask(st, CURRENT_Q, [{"claims": [_claim("c1", old)], "missing_evidence": []},
                                     {"claims": [_claim("r1", new)], "missing_evidence": []}])
    assert len(llm.calls) == 2 and "REPAIR ROUND" in llm.calls[1]
    assert [c.citations[0].doc_id for c in resp.claims] == ["acme_loan_policy_v3"] and resp.blocked_claims_count == 1


def test_older_version_history_and_conflict_questions_work_normally():
    st = sample_store()
    old = _sentence(st, "acme_loan_policy_v1", "late payment")
    ids = {d for d in st.documents}
    for q in ("What was the late payment fee in v1?", "What about in v1?", "What changed between versions?",
              "What was the earlier late payment fee?", "Are there any conflicting rules on late payment fees?"):
        assert superseded_for_current_rule(q, ids, st) == {}, q
    assert superseded_for_current_rule(CURRENT_Q, ids, st)  # ...but a current-rule question does tag
    resp, llm = _ask(st, "What was the late payment fee in v1?", [{"claims": [_claim("c1", old)], "missing_evidence": []}])
    assert "SUPERSEDED BY" not in llm.calls[0]
    assert [c.citations[0].doc_id for c in resp.claims] == ["acme_loan_policy_v1"] and resp.blocked_claims_count == 0


def test_no_dropping_when_the_amending_document_was_not_retrieved():
    st = sample_store()
    assert superseded_for_current_rule(CURRENT_Q, {"acme_loan_policy_v1", "acme_loan_policy_v2"}, st) == \
        {"acme_loan_policy_v1": "Acme_Loan_Policy_v2.pdf"}
    assert superseded_for_current_rule(CURRENT_Q, {"acme_loan_policy_v1"}, st) == {}


# ------------------------------------------------------------------ giant table-cell filter
def _chunk(cid, kind, texts):
    sents = [Sentence(sentence_id=f"{cid}#s{i}", chunk_id=cid, text=t, page=1) for i, t in enumerate(texts)]
    return RetrievedChunk(chunk=Chunk(chunk_id=cid, doc_id="d", doc_name="d.pdf", page=1, text=" ".join(texts), sentences=sents,
                                      chunk_type=kind), score=1.0)


GIANT = "(New section inserted) Penal Charges | " + "Penalty if charged for non-compliance shall be treated as penal charges. " * 10
SMALL_ROW = "Processing Fee | INR 1,000 | At disbursement"


def test_giant_table_rows_are_skipped_when_body_sentences_exist():
    assert len(GIANT) > MAX_TABLE_ROW_CHARS
    body = _chunk("d_p1_c1", "paragraph", ["Penal charges shall be reasonable and non-discriminatory."])
    table = _chunk("d_p1_c2", "table", [GIANT, SMALL_ROW])
    prompt = build_claim_prompt("What are the penal charges?", [body, table], {})
    assert "Penal charges shall be reasonable" in prompt and SMALL_ROW in prompt  # clean body + normal rows stay
    assert "(New section inserted)" not in prompt and "d_p1_c2#s0" not in prompt
    only_table = build_claim_prompt("What are the penal charges?", [_chunk("d_p1_c2", "table", [GIANT])], {})
    assert "(New section inserted)" in only_table  # nothing cleaner exists: keep the evidence
    long_prose = _chunk("d_p1_c3", "paragraph", ["A long but ordinary body sentence. " * 30])
    assert "A long but ordinary body sentence." in build_claim_prompt("q", [long_prose, table], {})  # prose is never filtered


# ------------------------------------------------------------------ repair claim that forgot its source ids
def test_repair_claim_without_source_ids_gets_the_one_sentence_it_restates():
    st = sample_store()
    old = _sentence(st, "acme_loan_policy_v1", "late payment")
    new = _sentence(st, "acme_loan_policy_v3", "2% per month")
    forgot = {"claim_id": "r1", "text": new.text, "claim_type": "numeric", "source_ids": []}
    resp, llm = _ask(st, CURRENT_Q, [{"claims": [_claim("c1", old)], "missing_evidence": []},
                                     {"claims": [forgot], "missing_evidence": []}])
    assert len(llm.calls) == 2
    assert [c.citations[0].sentence_id for c in resp.claims] == [new.sentence_id] and resp.faithfulness_pct == 100.0


def test_unrelated_unsourced_claim_stays_blocked_at_gate_2():
    st = sample_store()
    old = _sentence(st, "acme_loan_policy_v1", "late payment")
    made_up = {"claim_id": "r1", "text": "The platinum tier waiver is 9% per quarter for gold members.", "claim_type": "numeric", "source_ids": []}
    resp, _ = _ask(st, CURRENT_Q, [{"claims": [_claim("c1", old)], "missing_evidence": []}, {"claims": [made_up], "missing_evidence": []}])
    assert not resp.claims and any(b.reason == "no_source_ids" for b in resp.blocked_claims)
