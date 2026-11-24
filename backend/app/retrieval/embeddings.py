from __future__ import annotations

import threading
from typing import Protocol

import numpy as np

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)


class EmbeddingProvider(Protocol):
    def embed(self, texts: list[str]) -> np.ndarray: ...


_LOAD_LOCK = threading.Lock()


class SentenceTransformerEmbeddingProvider:
    _instance: SentenceTransformerEmbeddingProvider | None = None
    _model_name: str | None = None
    _device: str | None = None

    def __init__(self, model_name: str | None = None, device: str | None = None):
        self.model_name = model_name or settings.embedding_model
        self.device = device or settings.embedding_device
        self._model = None

    @classmethod
    def get_instance(cls) -> SentenceTransformerEmbeddingProvider:
        model_name = settings.embedding_model
        device = settings.embedding_device
        if cls._instance is None or cls._model_name != model_name or cls._device != device:
            cls._instance = cls(model_name=model_name, device=device)
            cls._model_name = model_name
            cls._device = device
        return cls._instance

    def is_loaded(self) -> bool:
        return self._model is not None

    def _load(self):
        if self._model is not None:
            return
        # Double-checked locking: a startup warm-up and the first request must not each load their own copy
        # (that doubles RAM/disk I/O and breaks the 16 GB budget).
        with _LOAD_LOCK:
            if self._model is not None:
                return
            from sentence_transformers import SentenceTransformer

            logger.info("Loading embedding model %s on %s", self.model_name, self.device)
            self._model = SentenceTransformer(self.model_name, device=self.device)

    def embed(self, texts: list[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, 384), dtype=np.float32)
        self._load()
        vecs = self._model.encode(
            texts,
            batch_size=16,
            show_progress_bar=False,
            normalize_embeddings=True,
            convert_to_numpy=True,
        )
        return np.asarray(vecs, dtype=np.float32)


class FakeEmbeddingProvider:
    """Deterministic lightweight embedding for tests."""

    def __init__(self, dim: int = 64):
        self.dim = dim

    def embed(self, texts: list[str]) -> np.ndarray:
        vecs = np.zeros((len(texts), self.dim), dtype=np.float32)
        for i, text in enumerate(texts):
            for tok in text.lower().split():
                h = hash(tok) % self.dim
                vecs[i, h] += 1.0
            norm = np.linalg.norm(vecs[i])
            if norm > 0:
                vecs[i] /= norm
        return vecs
