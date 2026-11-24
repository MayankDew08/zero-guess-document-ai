from __future__ import annotations

from app.core.config import settings
from app.core.store import AppStore
from app.models.schemas import AmendmentEdge, Chunk, Document, DraftClaim, Sentence
from app.qa.llm import FakeLLMProvider
from app.qa.service import ask_question
from app.retrieval.embeddings import FakeEmbeddingProvider
from app.retrieval.reranker import FakeRerankerProvider
from app.verification.nli import FakeNLIProvider
from app.verification.numeric import check_numeric_date_match
from app.verification.pipeline import resolve_and_verify_claims


def _make_store() -> AppStore:
    store = AppStore()
    doc = Document(doc_id="doc1", doc_name="Doc1.pdf", file_path="/tmp/doc1.pdf", num_pages=1, ingested_at="now", chunks_created=1)
    chunk = Chunk(
        chunk_id="doc1_p1_c1",
        doc_id="doc1",
        doc_name="Doc1.pdf",
        page=1,
        text="The late payment fee is 2% per month after the due date.",
        normalized_text="the late payment fee is 2% per month after the due date.",
        sentences=[
            Sentence(sentence_id="doc1_p1_c1#s0", chunk_id="doc1_p1_c1", text="The late payment fee is 2% per month after the due date.", page=1)
        ],
    )
    store.add_document(doc, [chunk])
    return store


def test_citation_resolution_blocks_invalid_source_id():
    store = _make_store()
    nli = FakeNLIProvider()
    drafts = [DraftClaim(claim_id="c1", text="The late payment fee is 2% per month.", claim_type="numeric", source_ids=["doc1_p1_c1#s999"])]
    shown, blocked = resolve_and_verify_claims(drafts, store, nli)
    assert not shown
    assert len(blocked) == 1
    assert blocked[0].status == "blocked"
    assert "unresolved_source_id" in (blocked[0].reason or "")


def test_numeric_mismatch_blocks_claim():
    ok, reason = check_numeric_date_match("The fee is 5% per month.", "The late payment fee is 2% per month after the due date.")
    assert not ok
    assert reason is not None


def test_numeric_match_passes():
    ok, reason = check_numeric_date_match("The fee is 2% per month.", "The late payment fee is 2% per month after the due date.")
    assert ok
    assert reason is None


def test_nli_and_numeric_gate_blocks_mismatch_claim():
    store = _make_store()
    nli = FakeNLIProvider()
    drafts = [DraftClaim(claim_id="c1", text="The late payment fee is 5% per month.", claim_type="numeric", source_ids=["doc1_p1_c1#s0"])]
    shown, blocked = resolve_and_verify_claims(drafts, store, nli)
    # contradicted / unsupported claims are BLOCKED, never shown
    assert shown == []
    assert len(blocked) == 1 and blocked[0].status == "blocked"
    assert "contradicted_by_cited_evidence" in blocked[0].reason or "numeric_date_mismatch" in blocked[0].reason


def _ask(store, claims):
    return ask_question(
        question="What is the late payment fee?",
        app_store=store,
        embedding_provider=FakeEmbeddingProvider(),
        reranker_provider=FakeRerankerProvider(),
        nli_provider=FakeNLIProvider(),
        llm_provider=FakeLLMProvider(responses=[{"claims": claims, "missing_evidence": []},
                                                 {"claims": [], "missing_evidence": []}]),  # 2nd = scripted (empty) repair round
    )


def test_contradicted_claim_never_leaks_into_answer():
    resp = _ask(_make_store(), [
        {"claim_id": "c1", "text": "The late payment fee is 2% per month.", "claim_type": "numeric", "source_ids": ["doc1_p1_c1#s0"]},
        {"claim_id": "c2", "text": "The late payment fee is 9% per month.", "claim_type": "numeric", "source_ids": ["doc1_p1_c1#s0"]},
    ])
    assert [c.claim_id for c in resp.claims] == ["c1"]
    assert all(c.status == "supported" for c in resp.claims)
    assert [c.claim_id for c in resp.blocked_claims] == ["c2"]
    assert resp.blocked_claims_count == 1
    assert "9%" not in resp.answer
    assert resp.faithfulness_pct == 100.0 and resp.draft_support_pct == 50.0
    assert any("9%" in m for m in resp.missing_evidence)


def test_all_claims_blocked_means_abstain_with_missing_evidence():
    resp = _ask(_make_store(), [
        {"claim_id": "c1", "text": "The late payment fee is 9% per month.", "claim_type": "numeric", "source_ids": ["doc1_p1_c1#s0"]},
    ])
    assert resp.status == "abstained" and resp.claims == []
    assert resp.answer.startswith("I don't have proof")
    assert resp.blocked_claims_count == 1 and resp.missing_evidence


def test_crag_gate_abstains_below_threshold(monkeypatch):
    store = _make_store()
    # Force high threshold so CRAG fails
    monkeypatch.setattr(settings, "rerank_abstain_threshold", 0.99)
    resp = ask_question(
        question="What is the late payment fee?",
        app_store=store,
        embedding_provider=FakeEmbeddingProvider(),
        reranker_provider=FakeRerankerProvider(),
        nli_provider=FakeNLIProvider(),
        llm_provider=FakeLLMProvider(responses=[{"claims": [{"claim_id": "c1", "text": "The late payment fee is 2% per month.", "claim_type": "numeric", "source_ids": ["doc1_p1_c1#s0"]}], "missing_evidence": []}]),
    )
    assert resp.status == "abstained"
    assert resp.faithfulness_pct is None


def test_amendment_explained_conflict_not_contradiction(monkeypatch):
    store = AppStore()
    doc1 = Document(doc_id="policy_v1", doc_name="Policy_v1.pdf", file_path="/tmp/v1.pdf", num_pages=1, ingested_at="now", chunks_created=1)
    doc2 = Document(doc_id="policy_v2", doc_name="Policy_v2.pdf", file_path="/tmp/v2.pdf", num_pages=1, ingested_at="now", chunks_created=1)
    c1 = Chunk(chunk_id="policy_v1_p1_c1", doc_id="policy_v1", doc_name="Policy_v1.pdf", page=1,
               text="The interest rate is 5% per year.", normalized_text="the interest rate is 5% per year.",
               sentences=[Sentence(sentence_id="policy_v1_p1_c1#s0", chunk_id="policy_v1_p1_c1", text="The interest rate is 5% per year.", page=1)])
    c2 = Chunk(chunk_id="policy_v2_p1_c1", doc_id="policy_v2", doc_name="Policy_v2.pdf", page=1,
               text="The interest rate is 7% per year. This amends Policy_v1 effective 2025-01-01.", normalized_text="the interest rate is 7% per year. this amends policy_v1 effective 2025-01-01.",
               sentences=[Sentence(sentence_id="policy_v2_p1_c1#s0", chunk_id="policy_v2_p1_c1", text="The interest rate is 7% per year.", page=1),
                          Sentence(sentence_id="policy_v2_p1_c1#s1", chunk_id="policy_v2_p1_c1", text="This amends Policy_v1 effective 2025-01-01.", page=1)])
    store.add_document(doc1, [c1])
    store.add_document(doc2, [c2])
    store.amendment_edges = [AmendmentEdge(edge_id="ame_1", from_doc_id="policy_v1", from_doc_name="Policy_v1.pdf", to_doc_id="policy_v2", to_doc_name="Policy_v2.pdf", relation="AMENDS", effective_date="2025-01-01", change_subject="interest rate", evidence_chunk_id="policy_v2_p1_c1", evidence_sentence_id="policy_v2_p1_c1#s1", evidence_page=1, evidence_quote="This amends Policy_v1 effective 2025-01-01.")]

    monkeypatch.setattr(settings, "rerank_abstain_threshold", 0.0)
    resp = ask_question(
        question="What is the interest rate?",
        app_store=store,
        embedding_provider=FakeEmbeddingProvider(),
        reranker_provider=FakeRerankerProvider(),
        nli_provider=FakeNLIProvider(),
        llm_provider=FakeLLMProvider(responses=[{"claims": [
            {"claim_id": "c1", "text": "The interest rate is 5% per year.", "claim_type": "numeric", "source_ids": ["policy_v1_p1_c1#s0"]},
            {"claim_id": "c2", "text": "The interest rate is 7% per year.", "claim_type": "numeric", "source_ids": ["policy_v2_p1_c1#s0"]},
        ], "missing_evidence": []}]),
    )
    # Should not flag as contradiction because amendment explains it
    assert not any(c.status == "confirmed" and c.subject == "interest rate" for c in resp.contradictions)


def test_faithfulness_reports_blocked_claims(monkeypatch):
    store = _make_store()
    monkeypatch.setattr(settings, "rerank_abstain_threshold", 0.0)
    resp = ask_question(
        question="What is the late payment fee?",
        app_store=store,
        embedding_provider=FakeEmbeddingProvider(),
        reranker_provider=FakeRerankerProvider(),
        nli_provider=FakeNLIProvider(),
        llm_provider=FakeLLMProvider(responses=[{"claims": [
            {"claim_id": "c1", "text": "The late payment fee is 2% per month.", "claim_type": "numeric", "source_ids": ["doc1_p1_c1#s0"]},
            {"claim_id": "c2", "text": "The late payment fee is 10% per month.", "claim_type": "numeric", "source_ids": ["doc1_p1_c1#s0"]},
        ], "missing_evidence": []}]),
    )
    # The 10% claim must not be supported; it should be blocked or contradicted
    assert resp.faithfulness_pct == 100.0
    assert resp.verified_sentences_count == 1
    assert resp.blocked_claims_count == 1


def test_malformed_source_id_is_format_repaired_but_never_invented():
    from app.verification.pipeline import repair_source_id

    store = _make_store()
    assert repair_source_id("doc1_p1_c1#0", store) == "doc1_p1_c1#s0"
    assert repair_source_id("doc1_p1_c1#s0", store) == "doc1_p1_c1#s0"
    assert repair_source_id("doc1_p1_c1#7", store) == "doc1_p1_c1#7"  # does not exist -> stays invalid
    shown, blocked = resolve_and_verify_claims(
        [DraftClaim(claim_id="c1", text="The late payment fee is 2% per month.", claim_type="numeric", source_ids=["doc1_p1_c1#0"])],
        store, FakeNLIProvider())
    assert len(shown) == 1 and shown[0].source_ids == ["doc1_p1_c1#s0"] and not blocked


def test_llm_placeholder_claim_type_does_not_crash_parsing():
    from app.qa.service import _parse_draft

    d = _parse_draft({"claims": [{"claim_id": "c1", "text": "x is 2%", "claim_type": "numeric|rule", "source_ids": ["a#s0"]},
                                 {"claim_id": "c2", "text": "y", "claim_type": "weird", "source_ids": []}]})
    assert [c.claim_type for c in d.claims] == ["numeric", "factual"]


class _BorrowerNLI:
    """Mimics the real mDeBERTa behaviour: 'Borrowers' substituted for 'Applicants' is scored as contradiction."""
    def predict(self, premise: str, hypothesis: str) -> dict[str, float]:
        if "Borrowers" in hypothesis:
            return {"entailment": 0.01, "neutral": 0.02, "contradiction": 0.97}
        return {"entailment": 0.97, "neutral": 0.02, "contradiction": 0.01}


def test_synonym_only_claim_is_regrounded_to_the_cited_sentence():
    from app.models.schemas import DraftClaim
    from app.verification.pipeline import resolve_and_verify_claims
    from tests.helpers import sample_store
    st = sample_store()
    sid = "acme_loan_policy_v3_p2_c2#s0"
    draft = DraftClaim(claim_id="c1", text="Borrowers must be between 21 and 60 years of age at the time of application",
                       claim_type="factual", source_ids=[sid])
    shown, blocked = resolve_and_verify_claims([draft], st, _BorrowerNLI())
    assert not blocked and len(shown) == 1
    assert shown[0].text == "Applicants must be between 21 and 60 years of age at the time of application."


def test_real_numeric_conflict_is_still_blocked_not_regrounded():
    from app.models.schemas import DraftClaim
    from app.verification.pipeline import resolve_and_verify_claims
    from tests.helpers import sample_store
    st = sample_store()
    draft = DraftClaim(claim_id="c1", text="Borrowers must have a minimum credit score of 680 to qualify for a standard personal loan",
                       claim_type="numeric", source_ids=["acme_loan_policy_v3_p2_c2#s1"])
    shown, blocked = resolve_and_verify_claims([draft], st, _BorrowerNLI())
    assert not shown and len(blocked) == 1
    assert "numeric_date_mismatch" in (blocked[0].reason or "")
