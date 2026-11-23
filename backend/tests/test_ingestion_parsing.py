from __future__ import annotations

import sys
from pathlib import Path

import pymupdf

from app.core.text import normalize_text
from tests.helpers import SAMPLES, sample_store

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))


def test_corpus_is_exactly_the_four_pdfs_with_expected_pages():
    pdfs = {p.name: len(pymupdf.open(p)) for p in SAMPLES.glob("*.pdf")}
    assert pdfs == {"Acme_Loan_Policy_v1.pdf": 2, "Acme_Loan_Policy_v2.pdf": 2,
                    "Acme_Loan_Policy_v3.pdf": 3, "Acme_Operations_Notice.pdf": 2}


def test_ingestion_produces_many_chunks_including_tables():
    st = sample_store()
    chunks = st.all_chunks()
    assert len(chunks) > 15
    tables = [c for c in chunks if c.chunk_type == "table"]
    assert tables and all(c.doc_name == "Acme_Loan_Policy_v3.pdf" for c in tables)
    rows = [s.text for s in tables[0].sentences]
    assert any(r.startswith("Processing Fee | INR 1,000") for r in rows)
    assert any(r.startswith("Bounce Charge | INR 750") for r in rows)
    assert len(rows) == 4  # one sentence per data row, header excluded
    assert tables[0].metadata["table_header"] == "Fee Type | Amount | When Applied"


def test_multi_page_clause_keeps_its_section_across_pages():
    st = sample_store()
    v3 = [c for c in st.all_chunks() if c.doc_id == "acme_loan_policy_v3" and c.section and "Eligibility" in c.section]
    assert {c.page for c in v3} == {2, 3}
    text = " ".join(s.text for c in v3 for s in c.sentences)
    for tag in ("(a)", "(c)", "(d)", "(f)"):
        assert tag in text
    p3 = next(c for c in v3 if c.page == 3)
    assert p3.section == "5. Eligibility and Repayment Conditions"  # carried over the page break


def test_headings_are_sections_never_sentences():
    st = sample_store()
    headings = {c.section for c in st.all_chunks()}
    for c in st.all_chunks():
        assert c.section
        for s in c.sentences:
            assert s.text not in headings, s.text


def test_quotes_are_verbatim_on_the_cited_page_and_bbox_is_tight():
    st = sample_store()
    page_text: dict[tuple[str, int], str] = {}
    for d in st.documents.values():
        pdf = pymupdf.open(d.file_path)
        for i, pg in enumerate(pdf):
            page_text[(d.doc_id, i + 1)] = normalize_text(pg.get_text())
    for c in st.all_chunks():
        for s in c.sentences:
            quote = s.text.replace(" | ", " ")  # table rows are cells joined by " | "
            assert quote in page_text[(c.doc_id, c.page)], (c.chunk_id, s.text)
            assert s.bbox is not None
            assert (s.bbox.y1 - s.bbox.y0) < 0.2 * s.bbox.page_height  # sentence-tight, not the whole page


def test_generator_script_regenerates_the_same_shape(tmp_path):
    import generate_samples

    out = generate_samples.generate_all(tmp_path)
    assert sorted(p.name for p in out) == sorted(p.name for p in SAMPLES.glob("*.pdf"))
    assert len(pymupdf.open(tmp_path / "Acme_Loan_Policy_v3.pdf")) == 3


def test_retrieval_pulls_in_the_continuation_of_a_multi_page_clause():
    from app.core.config import settings
    from app.retrieval.embeddings import FakeEmbeddingProvider
    from app.retrieval.reranker import FakeRerankerProvider
    from app.retrieval.service import retrieve

    st = sample_store()
    old = settings.rerank_abstain_threshold
    settings.rerank_abstain_threshold = 0.0
    try:
        res = retrieve("borrower eligibility conditions repayment", app_store=st, embedding_provider=FakeEmbeddingProvider(),
                       reranker_provider=FakeRerankerProvider(), doc_ids=["acme_loan_policy_v3"])
    finally:
        settings.rerank_abstain_threshold = old
    pages = {r.chunk.page for r in res.chunks if r.chunk.section and "Eligibility" in r.chunk.section}
    assert pages == {2, 3}
