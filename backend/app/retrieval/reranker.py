from __future__ import annotations

import threading
from typing import Protocol

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)


class RerankerProvider(Protocol):
    def rerank(self, query: str, texts: list[str]) -> list[float]: ...


_LOAD_LOCK = threading.Lock()


class CrossEncoderRerankerProvider:
    _instance: CrossEncoderRerankerProvider | None = None
    _model_name: str | None = None
    _device: str | None = None

    def __init__(self, model_name: str | None = None, device: str | None = None):
        self.model_name = model_name or settings.reranker_model
        self.device = device or settings.reranker_device
        self._model = None

    @classmethod
    def get_instance(cls) -> CrossEncoderRerankerProvider:
        model_name = settings.reranker_model
        device = settings.reranker_device
        if cls._instance is None or cls._model_name != model_name or cls._device != device:
            cls._instance = cls(model_name=model_name, device=device)
            cls._model_name = model_name
            cls._device = device
        return cls._instance

    def is_loaded(self) -> bool:
        return self._model is not None

    def preload(self) -> None:
        """Load now (startup warm-up) so the first question doesn't pay the ~14s model load as dead air."""
        self._load()

    def _load(self):
        if self._model is not None:
            return
        with _LOAD_LOCK:  # one load only, even if the startup warm-up and a request race
            if self._model is None:
                self._load_locked()

    def _load_locked(self):
        import torch
        from sentence_transformers import CrossEncoder

        logger.info("Loading reranker model %s on %s", self.model_name, self.device)
        model_kwargs = {}
        # fp16 only when explicitly placed on CUDA; default CPU keeps VRAM free for Ollama.
        if str(self.device).startswith("cuda") and settings.use_fp16 and torch.cuda.is_available():
            model_kwargs["torch_dtype"] = torch.float16
        try:
            self._model = CrossEncoder(
                self.model_name,
                device=self.device,
                model_kwargs=model_kwargs,
                trust_remote_code=False,
            )
        except Exception:
            self._model = CrossEncoder(self.model_name, device=self.device, trust_remote_code=False)

    def rerank(self, query: str, texts: list[str]) -> list[float]:
        if not texts:
            return []
        self._load()
        pairs = [(query, t) for t in texts]
        scores = self._model.predict(pairs, batch_size=8, show_progress_bar=False)
        # Normalize sigmoid-ish for CRAG thresholding? bge-reranker returns raw logits; map via sigmoid for stable threshold.
        import math

        out = []
        for s in scores:
            s = float(s)
            out.append(1 / (1 + math.exp(-s)))
        return out


class FakeRerankerProvider:
    def rerank(self, query: str, texts: list[str]) -> list[float]:
        q = set(query.lower().split())
        scores = []
        for t in texts:
            toks = set(t.lower().split())
            overlap = len(q & toks) / max(1, len(q))
            scores.append(min(1.0, 0.1 + overlap))
        return scores
