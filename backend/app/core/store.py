from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.models.schemas import AmendmentEdge, Chunk, Document


@dataclass
class AppStore:
    documents: dict[str, Document] = field(default_factory=dict)
    chunks: dict[str, Chunk] = field(default_factory=dict)
    sentence_index: dict[str, dict[str, Any]] = field(default_factory=dict)  # sentence_id -> {chunk_id, ...}
    amendment_edges: list[AmendmentEdge] = field(default_factory=list)
    # Retrieval runtime artifacts (not persisted as JSON except optionally)
    bm25 = None
    bm25_chunk_ids: list[str] = field(default_factory=list)
    embeddings = None  # numpy array
    embedding_chunk_ids: list[str] = field(default_factory=list)
    workspace: str = "bank_official"

    def reset(self) -> None:
        self.documents.clear()
        self.chunks.clear()
        self.sentence_index.clear()
        self.amendment_edges.clear()
        self.bm25 = None
        self.bm25_chunk_ids = []
        self.embeddings = None
        self.embedding_chunk_ids = []

    def add_document(self, doc: Document, chunks: list[Chunk]) -> None:
        self.documents[doc.doc_id] = doc
        for chunk in chunks:
            self.chunks[chunk.chunk_id] = chunk
            for s in chunk.sentences:
                self.sentence_index[s.sentence_id] = {
                    "sentence_id": s.sentence_id,
                    "chunk_id": chunk.chunk_id,
                    "doc_id": chunk.doc_id,
                    "doc_name": chunk.doc_name,
                    "page": chunk.page,
                    "section_context": chunk.section_context or chunk.section or "",
                    "text": s.text,
                    "bbox": s.bbox.model_dump() if s.bbox else None,
                }

    def get_sentence(self, sentence_id: str) -> dict[str, Any] | None:
        return self.sentence_index.get(sentence_id)

    def get_chunk(self, chunk_id: str) -> Chunk | None:
        return self.chunks.get(chunk_id)

    def all_chunks(self, doc_ids: list[str] | None = None) -> list[Chunk]:
        chunks = list(self.chunks.values())
        if doc_ids is not None:
            allowed = set(doc_ids)
            chunks = [c for c in chunks if c.doc_id in allowed]
        return chunks

    def save(self, index_dir: str | Path) -> None:
        path = Path(index_dir)
        path.mkdir(parents=True, exist_ok=True)
        (path / "documents.json").write_text(
            json.dumps([d.model_dump() for d in self.documents.values()], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        (path / "chunks.json").write_text(
            json.dumps([c.model_dump() for c in self.chunks.values()], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        (path / "amendments.json").write_text(
            json.dumps([e.model_dump() for e in self.amendment_edges], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def load(self, index_dir: str | Path) -> bool:
        path = Path(index_dir)
        docs_file = path / "documents.json"
        chunks_file = path / "chunks.json"
        if not docs_file.exists() or not chunks_file.exists():
            return False
        self.reset()
        docs = json.loads(docs_file.read_text(encoding="utf-8"))
        chunks = json.loads(chunks_file.read_text(encoding="utf-8"))
        for d in docs:
            self.documents[d["doc_id"]] = Document.model_validate(d)
        for c in chunks:
            chunk = Chunk.model_validate(c)
            self.chunks[chunk.chunk_id] = chunk
            for s in chunk.sentences:
                self.sentence_index[s.sentence_id] = {
                    "sentence_id": s.sentence_id,
                    "chunk_id": chunk.chunk_id,
                    "doc_id": chunk.doc_id,
                    "doc_name": chunk.doc_name,
                    "page": chunk.page,
                    "section_context": chunk.section_context or chunk.section or "",
                    "text": s.text,
                    "bbox": s.bbox.model_dump() if s.bbox else None,
                }
        am_file = path / "amendments.json"
        if am_file.exists():
            ams = json.loads(am_file.read_text(encoding="utf-8"))
            self.amendment_edges = [AmendmentEdge.model_validate(a) for a in ams]
        return True


# --------------------------------------------------------------------------- workspaces
# Each workspace owns an isolated AppStore (documents, chunks, sentences, amendment graph, BM25 + vectors).
# The heavy ML models (bge-m3, bge-reranker-v2-m3, mDeBERTa NLI) are process-wide singletons and are NOT
# part of the store, so adding a workspace costs no extra model RAM (only its own small vector matrix).
DEFAULT_WORKSPACE = "bank_official"
WORKSPACES: tuple[str, ...] = ("bank_official", "byo_private")

# `store` is the bank_official corpus (kept as a module global for backwards compatibility).
store = AppStore(workspace=DEFAULT_WORKSPACE)
_stores: dict[str, AppStore] = {DEFAULT_WORKSPACE: store, "byo_private": AppStore(workspace="byo_private")}


def is_valid_workspace(workspace: str) -> bool:
    return workspace in WORKSPACES


def get_store(workspace: str = DEFAULT_WORKSPACE) -> AppStore:
    """The isolated store of a workspace. Raises ValueError for unknown workspaces."""
    if workspace not in _stores:
        raise ValueError(f"Unknown workspace '{workspace}'. Valid: {', '.join(WORKSPACES)}")
    if workspace == DEFAULT_WORKSPACE:
        return store
    return _stores[workspace]
