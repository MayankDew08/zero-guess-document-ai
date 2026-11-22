from __future__ import annotations

import re

from rank_bm25 import BM25Okapi

from app.models.schemas import Chunk


_TOKEN_RE = re.compile(r"[a-zA-Z0-9%₹$€£./:-]+")


def tokenize(text: str) -> list[str]:
    return [t.lower() for t in _TOKEN_RE.findall(text or "")]


class BM25Index:
    def __init__(self, chunks: list[Chunk]):
        self.chunks = chunks
        self.chunk_ids = [c.chunk_id for c in chunks]
        corpus = [tokenize(c.text) for c in chunks]
        self.bm25 = BM25Okapi(corpus) if corpus else None

    def search(self, query: str, top_k: int = 12) -> list[tuple[str, float]]:
        if not self.bm25 or not self.chunks:
            return []
        scores = self.bm25.get_scores(tokenize(query))
        ranked = sorted(enumerate(scores), key=lambda x: x[1], reverse=True)[:top_k]
        return [(self.chunk_ids[i], float(s)) for i, s in ranked if s > 0]
