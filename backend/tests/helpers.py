from __future__ import annotations

from pathlib import Path

from app.amendments.graph import extract_amendment_edges
from app.core.store import AppStore
from app.ingestion.chunker import chunk_pages
from app.ingestion.parser import parse_pdf
from app.models.schemas import Document

SAMPLES = Path(__file__).resolve().parents[2] / "data" / "samples"


def sample_store(exclude: tuple[str, ...] = ()) -> AppStore:
    """Parse the real sample PDFs into an isolated store (no models, no global state)."""
    st = AppStore()
    names: dict[str, str] = {}
    for pdf in sorted(SAMPLES.glob("*.pdf")):
        if pdf.stem in exclude:
            continue
        doc_id = pdf.stem.lower()
        pages = parse_pdf(pdf)
        chunks = chunk_pages(doc_id, pdf.name, pages)
        names[doc_id] = pdf.name
        st.add_document(Document(doc_id=doc_id, doc_name=pdf.name, file_path=str(pdf), num_pages=len(pages),
                                 ingested_at="test", chunks_created=len(chunks)), chunks)
    st.amendment_edges = extract_amendment_edges(st.all_chunks(), names)
    return st
