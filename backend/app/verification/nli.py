from __future__ import annotations

from typing import Protocol

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)


class NLIProvider(Protocol):
    def predict(self, premise: str, hypothesis: str) -> dict[str, float]: ...


class HFNLIProvider:
    _instance: HFNLIProvider | None = None
    _model_name: str | None = None
    _device: str | None = None

    def __init__(self, model_name: str | None = None, device: str | None = None):
        self.model_name = model_name or settings.nli_model
        self.device = device or settings.nli_device
        self._pipe = None

    @classmethod
    def get_instance(cls) -> HFNLIProvider:
        model_name = settings.nli_model
        device = settings.nli_device
        if cls._instance is None or cls._model_name != model_name or cls._device != device:
            cls._instance = cls(model_name=model_name, device=device)
            cls._model_name = model_name
            cls._device = device
        return cls._instance

    def is_loaded(self) -> bool:
        return self._pipe is not None

    def _load(self):
        if self._pipe is not None:
            return
        import torch
        from transformers import pipeline

        logger.info("Loading NLI model %s on %s", self.model_name, self.device)
        kwargs = {"task": "text-classification", "model": self.model_name, "top_k": None}
        if str(self.device).startswith("cuda") and settings.use_fp16 and torch.cuda.is_available():
            kwargs["torch_dtype"] = torch.float16
            kwargs["device"] = 0
        else:
            # CPU or explicit non-cuda
            kwargs["device"] = -1
        try:
            self._pipe = pipeline(**kwargs)
        except Exception:
            kwargs.pop("torch_dtype", None)
            self._pipe = pipeline(**kwargs)

    def predict(self, premise: str, hypothesis: str) -> dict[str, float]:
        self._load()
        # mDeBERTa-v3-base-mnli-xnli returns labels entailment/neutral/contradiction
        result = self._pipe({"text": premise, "text_pair": hypothesis}, truncation=True)
        # pipeline returns list of list[dict(label,score)] when top_k=None
        scores_list = result[0] if isinstance(result, list) and result and isinstance(result[0], list) else result
        scores = {"entailment": 0.0, "neutral": 0.0, "contradiction": 0.0}
        for item in scores_list:
            label = str(item.get("label", "")).lower()
            score = float(item.get("score", 0.0))
            if "entail" in label:
                scores["entailment"] = score
            elif "contrad" in label:
                scores["contradiction"] = score
            elif "neutral" in label:
                scores["neutral"] = score
        # normalize in case of rounding
        total = sum(scores.values()) or 1.0
        for k in scores:
            scores[k] = scores[k] / total
        return scores


class FakeNLIProvider:
    """Simple heuristic NLI for tests."""

    def predict(self, premise: str, hypothesis: str) -> dict[str, float]:
        p = premise.lower()
        h = hypothesis.lower()
        # Numeric contradiction heuristic
        p_nums = _nums(p)
        h_nums = _nums(h)
        if h_nums and p_nums and not h_nums.issubset(p_nums):
            # if hypothesis has numbers not in premise, likely contradiction/neutral
            overlap = len(h_nums & p_nums) / max(1, len(h_nums))
            if overlap == 0:
                return {"entailment": 0.05, "neutral": 0.15, "contradiction": 0.80}
            return {"entailment": 0.2, "neutral": 0.6, "contradiction": 0.2}
        h_tokens = set(h.split())
        p_tokens = set(p.split())
        overlap = len(h_tokens & p_tokens) / max(1, len(h_tokens))
        if overlap > 0.7:
            return {"entailment": 0.9, "neutral": 0.08, "contradiction": 0.02}
        if overlap > 0.4:
            return {"entailment": 0.6, "neutral": 0.3, "contradiction": 0.1}
        return {"entailment": 0.1, "neutral": 0.7, "contradiction": 0.2}


def _nums(text: str) -> set[str]:
    import re

    return set(re.findall(r"\d+(?:\.\d+)?", text))
