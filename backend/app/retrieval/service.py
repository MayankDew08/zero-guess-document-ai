from __future__ import annotations

import numpy as np

from app.core.config import settings
from app.core.logging import get_logger
from app.core.store import AppStore, store
from app.models.schemas import RetrievedChunk, RetrievalResult
from app.retrieval.bm25_index import BM25Index
from app.retrieval.embeddings import EmbeddingProvider, SentenceTransformerEmbeddingProvider
from app.retrieval.reranker import CrossEncoderRerankerProvider, RerankerProvider

logger = get_logger(__name__)


def build_index(app_store: AppStore = store, embedding_provider: EmbeddingProvider | None = None) -> None:
    chunks = app_store.all_chunks()
    if not chunks:
        app_store.bm25 = None
        app_store.bm25_chunk_ids = []
        app_store.embeddings = None
        app_store.embedding_chunk_ids = []
        return
    app_store.bm25 = BM25Index(chunks)
    app_store.bm25_chunk_ids = [c.chunk_id for c in chunks]
    provider = embedding_provider
    if provider is None:
        try:
            provider = SentenceTransformerEmbeddingProvider.get_instance()
        except Exception as e:
            logger.warning("Embedding model unavailable, falling back to FakeEmbeddingProvider: %s", e)
            from app.retrieval.embeddings import FakeEmbeddingProvider
            provider = FakeEmbeddingProvider()
    texts = [c.text for c in chunks]
    try:
        app_store.embeddings = provider.embed(texts)
    except Exception as e:
        logger.warning("Embedding failed, falling back to FakeEmbeddingProvider: %s", e)
        from app.retrieval.embeddings import FakeEmbeddingProvider
        app_store.embeddings = FakeEmbeddingProvider().embed(texts)
    app_store.embedding_chunk_ids = [c.chunk_id for c in chunks]
    logger.info("Built index for %s chunks", len(chunks))


def _cosine_search(query_vec: np.ndarray, matrix: np.ndarray, top_k: int) -> list[tuple[int, float]]:
    if matrix is None or len(matrix) == 0:
        return []
    # matrix and query_vec assumed normalized
    scores = matrix @ query_vec.reshape(-1)
    idxs = np.argsort(-scores)[:top_k]
    return [(int(i), float(scores[i])) for i in idxs]


def _rrf_fuse(rank_lists: list[list[str]], k: int = 60) -> dict[str, float]:
    fused: dict[str, float] = {}
    for lst in rank_lists:
        for rank, chunk_id in enumerate(lst, start=1):
            fused[chunk_id] = fused.get(chunk_id, 0.0) + 1.0 / (k + rank)
    return fused


def retrieve(
    query: str,
    top_k: int | None = None,
    doc_ids: list[str] | None = None,
    app_store: AppStore = store,
    embedding_provider: EmbeddingProvider | None = None,
    reranker_provider: RerankerProvider | None = None,
    apply_reranker: bool = True,
    apply_crag_gate: bool = True,
) -> RetrievalResult:
    top_k = top_k or settings.hybrid_top_k
    chunks = app_store.all_chunks(doc_ids=doc_ids)
    if not chunks:
        return RetrievalResult(query=query, chunks=[], total_indexed_chunks=0, crag_passed=False, max_rerank_score=None)

    # Build per-query filtered indices if doc_ids filter or index missing
    if app_store.bm25 is None or app_store.embeddings is None or doc_ids:
        filtered_store_chunks = chunks
        bm25 = BM25Index(filtered_store_chunks)
        bm25_ids = [c.chunk_id for c in filtered_store_chunks]
        provider = embedding_provider or SentenceTransformerEmbeddingProvider.get_instance()
        emb = provider.embed([c.text for c in filtered_store_chunks])
        emb_ids = bm25_ids
    else:
        bm25 = app_store.bm25
        bm25_ids = app_store.bm25_chunk_ids
        emb = app_store.embeddings
        emb_ids = app_store.embedding_chunk_ids

    bm25_hits = bm25.search(query, top_k=top_k)
    bm25_ranked = [cid for cid, _ in bm25_hits]
    bm25_scores = {cid: s for cid, s in bm25_hits}

    provider = embedding_provider or SentenceTransformerEmbeddingProvider.get_instance()
    qvec = provider.embed([query])
    sem_hits = _cosine_search(qvec[0], emb, top_k=top_k) if len(qvec) else []
    sem_ranked = [emb_ids[i] for i, _ in sem_hits if i < len(emb_ids)]
    sem_scores = {emb_ids[i]: s for i, s in sem_hits if i < len(emb_ids)}

    fused = _rrf_fuse([sem_ranked, bm25_ranked])
    # Keep only chunks in allowed set
    allowed = set(c.chunk_id for c in chunks)
    fused = {cid: s for cid, s in fused.items() if cid in allowed}
    ranked_ids = sorted(fused.keys(), key=lambda c: fused[c], reverse=True)[:top_k]

    retrieved: list[RetrievedChunk] = []
    for rank, cid in enumerate(ranked_ids, start=1):
        chunk = app_store.get_chunk(cid)
        if not chunk:
            continue
        retrieved.append(
            RetrievedChunk(
                chunk=chunk,
                score=float(fused.get(cid, 0.0)),
                semantic_score=sem_scores.get(cid),
                bm25_score=bm25_scores.get(cid),
                rerank_score=None,
                retrieval_rank=rank,
            )
        )

    max_rerank = None
    crag_passed = True
    if apply_reranker and retrieved:
        reranker = reranker_provider
        if reranker is None:
            try:
                reranker = CrossEncoderRerankerProvider.get_instance()
            except Exception as e:
                logger.warning("Reranker unavailable, falling back to FakeRerankerProvider: %s", e)
                from app.retrieval.reranker import FakeRerankerProvider
                reranker = FakeRerankerProvider()
        try:
            scores = reranker.rerank(query, [r.chunk.text for r in retrieved])
        except Exception as e:
            logger.warning("Reranking failed, falling back to FakeRerankerProvider: %s", e)
            from app.retrieval.reranker import FakeRerankerProvider
            scores = FakeRerankerProvider().rerank(query, [r.chunk.text for r in retrieved])
        for r, s in zip(retrieved, scores):
            r.rerank_score = float(s)
        retrieved.sort(key=lambda r: (r.rerank_score or 0.0), reverse=True)
        for i, r in enumerate(retrieved, start=1):
            r.retrieval_rank = i
        retrieved = retrieved[: settings.reranker_keep_top_n]
        max_rerank = max((r.rerank_score or 0.0) for r in retrieved) if retrieved else 0.0
        if apply_crag_gate:
            crag_passed = (max_rerank or 0.0) >= settings.rerank_abstain_threshold

    return RetrievalResult(
        query=query,
        chunks=retrieved,
        total_indexed_chunks=len(app_store.chunks),
        crag_passed=crag_passed,
        max_rerank_score=max_rerank,
    )
