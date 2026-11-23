from __future__ import annotations

import shutil
from datetime import UTC, datetime
from pathlib import Path

from app.amendments.graph import extract_amendment_edges, extract_reference_ids
from app.core.config import settings
from app.core.logging import get_logger
from app.core.store import AppStore, store
from app.core.text import slugify, stable_hash
from app.ingestion.chunker import chunk_pages
from app.ingestion.parser import parse_pdf
from app.models.schemas import Document

logger = get_logger(__name__)


def _st(app_store: AppStore | None) -> AppStore:
    """Explicit store (a workspace) or, by default, the bank_official global (read at call time)."""
    return app_store if app_store is not None else store


def ingest_pdf_file(path: str | Path, original_name: str | None = None, app_store: AppStore | None = None) -> Document:
    st = _st(app_store)
    path = Path(path)
    doc_name = original_name or path.name
    doc_id = _doc_id_for(doc_name, st)
    pages = parse_pdf(path)
    chunks = chunk_pages(
        doc_id=doc_id,
        doc_name=doc_name,
        pages=pages,
        target_chars=settings.chunk_target_chars,
        overlap_chars=settings.chunk_overlap_chars,
    )
    docs_dir = settings.documents_path_for(st.workspace)
    docs_dir.mkdir(parents=True, exist_ok=True)
    dest = docs_dir / doc_name
    if path.resolve() != dest.resolve():
        try:
            shutil.copy2(path, dest)
        except Exception:
            dest = path
    doc = Document(
        doc_id=doc_id,
        doc_name=doc_name,
        file_path=str(dest),
        num_pages=len(pages),
        ingested_at=datetime.now(UTC).isoformat(),
        chunks_created=len(chunks),
        checksum=stable_hash(f"{doc_name}:{path.stat().st_size if path.exists() else 0}", 16),
        aliases=_page1_reference_ids(path),
    )
    _remove_doc(doc_id, st)
    st.add_document(doc, chunks)
    _rebuild_amendment_edges(st)
    logger.info("[%s] Ingested %s: %s pages, %s chunks", st.workspace, doc_name, doc.num_pages, doc.chunks_created)
    return doc


def ingest_path(path: str | Path, original_name: str | None = None, app_store: AppStore | None = None) -> list[Document]:
    """Ingest a PDF file or all PDFs in a directory."""
    path = Path(path)
    if path.is_dir():
        pdfs = sorted(path.glob("*.pdf"))
        docs: list[Document] = []
        for p in pdfs:
            docs.append(ingest_pdf_file(p, app_store=app_store))
        return docs
    if path.is_file():
        return [ingest_pdf_file(path, original_name=original_name, app_store=app_store)]
    raise FileNotFoundError(f"Path not found: {path}")


def ingest_samples(reset: bool = True, app_store: AppStore | None = None) -> tuple[list[Document], list[dict[str, str]]]:
    """Ingest all PDFs from the configured sample directory (clean slate by default)."""
    st = _st(app_store)
    if reset:
        st.reset()
    sample_dir = settings.sample_path
    if not sample_dir.exists():
        return [], [{"error": f"Sample directory not found: {sample_dir}"}]
    pdfs = sorted(sample_dir.glob("*.pdf"))
    if not pdfs:
        return [], [{"error": "No sample PDFs found. Run scripts/generate_samples.py first."}]
    documents: list[Document] = []
    errors: list[dict[str, str]] = []
    for p in pdfs:
        try:
            documents.append(ingest_pdf_file(p, app_store=st))
        except Exception as e:
            logger.exception("Sample ingest failed for %s", p.name)
            errors.append({"doc_name": p.name, "error": str(e)})
    return documents, errors


def rebuild_runtime_index(embedding_provider=None, app_store: AppStore | None = None) -> None:
    from app.retrieval.service import build_index

    st = _st(app_store)
    build_index(app_store=st, embedding_provider=embedding_provider)
    _rebuild_amendment_edges(st)
    st.save(settings.index_path_for(st.workspace))


def _page1_reference_ids(path: str | Path) -> list[str]:
    """Regulatory reference ids of a PDF's letterhead (raw page-1 text: running headers are not in the chunks)."""
    try:
        import pymupdf

        with pymupdf.open(str(path)) as pdf:
            return extract_reference_ids(pdf.load_page(0).get_text()) if len(pdf) else []
    except Exception as e:
        logger.warning("Could not read reference ids from %s: %s", path, e)
        return []


def _rebuild_amendment_edges(app_store: AppStore | None = None) -> None:
    st = _st(app_store)
    doc_name_by_id = {d.doc_id: d.doc_name for d in st.documents.values()}
    for d in st.documents.values():  # documents persisted before aliases existed: backfill from the stored PDF
        if not d.aliases and d.file_path and Path(d.file_path).exists():
            d.aliases = _page1_reference_ids(d.file_path)
    aliases = {d.doc_id: d.aliases for d in st.documents.values() if d.aliases}
    all_chunks = st.all_chunks()
    st.amendment_edges = extract_amendment_edges(all_chunks, doc_name_by_id, aliases)


def _remove_doc(doc_id: str, app_store: AppStore | None = None) -> None:
    st = _st(app_store)
    if doc_id in st.documents:
        del st.documents[doc_id]
    to_del = [cid for cid, c in st.chunks.items() if c.doc_id == doc_id]
    for cid in to_del:
        chunk = st.chunks.pop(cid, None)
        if chunk:
            for s in chunk.sentences:
                st.sentence_index.pop(s.sentence_id, None)
    st.amendment_edges = [e for e in st.amendment_edges if e.from_doc_id != doc_id and e.to_doc_id != doc_id]


def _doc_id_for(doc_name: str, app_store: AppStore | None = None) -> str:
    st = _st(app_store)
    base = slugify(Path(doc_name).stem)
    if base in st.documents and st.documents[base].doc_name != doc_name:
        base = f"{base}_{stable_hash(doc_name, 6)}"
    return base


def remove_document(doc_id: str, app_store: AppStore | None = None) -> None:
    """Delete a document and everything derived from it (chunks, sentences, edges, stored PDF copy)."""
    st = _st(app_store)
    doc = st.documents.get(doc_id)
    _remove_doc(doc_id, st)
    _rebuild_amendment_edges(st)
    if doc is not None:
        try:
            stored = Path(doc.file_path)
            if stored.parent.resolve() == settings.documents_path_for(st.workspace).resolve():
                stored.unlink(missing_ok=True)
        except Exception:
            logger.warning("Could not delete stored copy of %s", doc_id)


def clear_all_documents(app_store: AppStore | None = None) -> None:
    st = _st(app_store)
    for doc_id in list(st.documents):
        remove_document(doc_id, st)
    st.reset()
