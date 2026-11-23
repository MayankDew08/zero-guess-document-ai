from __future__ import annotations

from app.amendments.graph import (
    active_chain_doc_ids,
    build_amendment_chains,
    extract_amendment_edges,
    is_amendment_pair,
)
from app.contradictions.detector import (
    looks_like_heading,
    scan_corpus_contradictions,
    strip_section_number,
    typed_values,
)
from tests.helpers import sample_store


def test_edge_direction_newer_supersedes_older():
    st = sample_store()
    pairs = {(e.from_doc_name, e.relation, e.to_doc_name) for e in st.amendment_edges}
    assert ("Acme_Loan_Policy_v3.pdf", "SUPERSEDES", "Acme_Loan_Policy_v2.pdf") in pairs
    assert ("Acme_Loan_Policy_v2.pdf", "SUPERSEDES", "Acme_Loan_Policy_v1.pdf") in pairs


def test_edge_quote_is_the_clause_not_the_title():
    st = sample_store()
    assert st.amendment_edges
    for e in st.amendment_edges:
        assert "supersedes" in e.evidence_quote.lower()
        assert not e.evidence_quote.startswith("Acme Loan Policy - Version")
        assert e.evidence_sentence_id
        stored = st.get_sentence(e.evidence_sentence_id)
        assert stored and stored["text"] == e.evidence_quote


def test_chain_is_chronological_with_v3_active():
    st = sample_store()
    names = {d.doc_id: d.doc_name for d in st.documents.values()}
    (chain,) = build_amendment_chains(st.amendment_edges, names)
    assert chain.doc_names_ordered == ["Acme_Loan_Policy_v1.pdf", "Acme_Loan_Policy_v2.pdf", "Acme_Loan_Policy_v3.pdf"]
    assert chain.active_doc_name == "Acme_Loan_Policy_v3.pdf"
    assert active_chain_doc_ids(st.amendment_edges) == {"acme_loan_policy_v3"}


def test_transitive_amendment_pair_v1_v3_not_a_conflict():
    st = sample_store()
    assert is_amendment_pair("acme_loan_policy_v1", "acme_loan_policy_v3", st.amendment_edges)  # 2 hops
    assert is_amendment_pair("acme_loan_policy_v3", "acme_loan_policy_v1", st.amendment_edges)
    assert not is_amendment_pair("acme_operations_notice", "acme_loan_policy_v3", st.amendment_edges)


def test_corpus_scan_finds_only_the_real_conflicts_with_real_quotes():
    st = sample_store()
    found = scan_corpus_contradictions(st)
    assert {c.subject for c in found} == {"late payment fee", "grace period"}
    for c in found:
        docs = {v.doc_name for v in c.values}
        assert docs == {"Acme_Loan_Policy_v3.pdf", "Acme_Operations_Notice.pdf"}  # never v1/v2 vs v3
        for v in c.values:
            assert v.sentence_id
            stored = st.get_sentence(v.sentence_id)
            assert stored and v.quote == stored["text"]  # verbatim stored sentence
            assert not looks_like_heading(v.quote)
    fee = next(c for c in found if c.subject == "late payment fee")
    assert {v.normalized_value for v in fee.values} == {"2%", "5%"}
    grace = next(c for c in found if c.subject == "grace period")
    assert {v.normalized_value for v in grace.values} == {"15 days", "5 days"}


def test_no_false_conflict_without_the_notice():
    st = sample_store(exclude=("Acme_Operations_Notice",))
    assert scan_corpus_contradictions(st) == []


def test_heading_numbers_are_immune():
    assert strip_section_number("2. Late Payment Fee") == "Late Payment Fee"
    assert strip_section_number("4.1) Tenure of loan") == "Tenure of loan"
    assert typed_values("1. Interest Rate") == []  # a section number is not a value
    assert typed_values("2. Late Payment Fee") == []
    assert looks_like_heading("1. Interest Rate") and looks_like_heading("2. Late Payment Fee")
    assert not looks_like_heading("A late payment fee of 2% per month applies after the due date.")
    # unit-typed values only; bare numbers are ignored
    assert [v[0] for v in typed_values("Minimum credit score of 700 and a fee of 2% and Rs 500 within 15 days")] == [
        "percent", "currency", "duration:day"]


def test_passive_voice_edge_direction():
    from app.models.schemas import Chunk, Sentence

    t = "Acme Policy v1 is superseded by Acme Policy v2."
    ch = Chunk(chunk_id="acme_policy_v1_p1_c1", doc_id="acme_policy_v1", doc_name="Acme_Policy_v1.pdf", page=1, text=t,
               sentences=[Sentence(sentence_id="acme_policy_v1_p1_c1#s0", chunk_id="acme_policy_v1_p1_c1", text=t, page=1)])
    names = {"acme_policy_v1": "Acme_Policy_v1.pdf", "acme_policy_v2": "Acme_Policy_v2.pdf"}
    (e,) = extract_amendment_edges([ch], names)
    assert (e.from_doc_id, e.to_doc_id) == ("acme_policy_v2", "acme_policy_v1")
