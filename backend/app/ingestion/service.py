from __future__ import annotations

import shutil
from datetime import UTC, datetime
from pathlib import Path

from app.amendments.graph import extract_amendment_edges
from app.core.config import settings
from app.core.logging import get_logger
from app.core.store import store
from app.core.text import slugify, stable_hash
from app.ingestion.chunker import chunk_pages
from app.ingestion.parser import parse_pdf
from app.models.schemas import Document

logger = get_logger(__name__)


def ingest_pdf_file(path: str | Path, original_name: str | None = None) -> Document:
    path = Path(path)
    doc_name = original_name or path.name
    doc_id = _doc_id_for(doc_name)
    pages = parse_pdf(path)
    chunks = chunk_pages(
        doc_id=doc_id,
        doc_name=doc_name,
        pages=pages,
        target_chars=settings.chunk_target_chars,
        overlap_chars=settings.chunk_overlap_chars,
    )
    docs_dir = settings.data_path / "documents"
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
    )
    _remove_doc(doc_id)
    store.add_document(doc, chunks)
    _rebuild_amendment_edges()
    logger.info("Ingested %s: %s pages, %s chunks", doc_name, doc.num_pages, doc.chunks_created)
    return doc


def ingest_path(path: str | Path, original_name: str | None = None) -> list[Document]:
    """Ingest a PDF file or all PDFs in a directory."""
    path = Path(path)
    if path.is_dir():
        pdfs = sorted(path.glob("*.pdf"))
        docs: list[Document] = []
        for p in pdfs:
            docs.append(ingest_pdf_file(p))
        return docs
    if path.is_file():
        return [ingest_pdf_file(path, original_name=original_name)]
    raise FileNotFoundError(f"Path not found: {path}")


def ingest_samples(reset: bool = True) -> tuple[list[Document], list[dict[str, str]]]:
    """Ingest all PDFs from the configured sample directory (clean slate by default)."""
    if reset:
        store.reset()
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
            documents.append(ingest_pdf_file(p))
        except Exception as e:
            logger.exception("Sample ingest failed for %s", p.name)
            errors.append({"doc_name": p.name, "error": str(e)})
    return documents, errors


def rebuild_runtime_index(embedding_provider=None) -> None:
    from app.retrieval.service import build_index

    build_index(app_store=store, embedding_provider=embedding_provider)
    _rebuild_amendment_edges()
    store.save(settings.index_path)


def _rebuild_amendment_edges() -> None:
    doc_name_by_id = {d.doc_id: d.doc_name for d in store.documents.values()}
    all_chunks = store.all_chunks()
    store.amendment_edges = extract_amendment_edges(all_chunks, doc_name_by_id)


def _remove_doc(doc_id: str) -> None:
    if doc_id in store.documents:
        del store.documents[doc_id]
    to_del = [cid for cid, c in store.chunks.items() if c.doc_id == doc_id]
    for cid in to_del:
        chunk = store.chunks.pop(cid, None)
        if chunk:
            for s in chunk.sentences:
                store.sentence_index.pop(s.sentence_id, None)
    store.amendment_edges = [e for e in store.amendment_edges if e.from_doc_id != doc_id and e.to_doc_id != doc_id]


def _doc_id_for(doc_name: str) -> str:
    base = slugify(Path(doc_name).stem)
    if base in store.documents and store.documents[base].doc_name != doc_name:
        base = f"{base}_{stable_hash(doc_name, 6)}"
    return base
