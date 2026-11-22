from __future__ import annotations

import json
from typing import Any, Protocol

import httpx

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)


class LLMProvider(Protocol):
    def generate_json(self, prompt: str) -> dict[str, Any]: ...


class OllamaLLMProvider:
    def __init__(self, model: str | None = None, base_url: str | None = None):
        self.model = model or settings.ollama_model
        self.base_url = (base_url or settings.ollama_base_url).rstrip("/")

    def generate_json(self, prompt: str) -> dict[str, Any]:
        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "format": "json",
            "options": {
                "temperature": settings.llm_temperature,
                "num_predict": settings.llm_max_tokens,
            },
        }
        with httpx.Client(timeout=settings.llm_timeout_seconds) as client:
            resp = client.post(f"{self.base_url}/api/generate", json=payload)
            resp.raise_for_status()
            data = resp.json()
        raw = data.get("response", "")
        return _parse_json(raw)


class FakeLLMProvider:
    """For tests: returns preconfigured responses or a simple default."""

    def __init__(self, responses: list[dict[str, Any]] | None = None):
        self.responses = list(responses or [])
        self.calls: list[str] = []

    def generate_json(self, prompt: str) -> dict[str, Any]:
        self.calls.append(prompt)
        if self.responses:
            return self.responses.pop(0)
        return {"claims": [], "missing_evidence": ["No evidence provided to fake LLM."]}


def _parse_json(raw: str) -> dict[str, Any]:
    raw = (raw or "").strip()
    if not raw:
        return {"claims": [], "missing_evidence": ["Empty LLM response"]}
    # Try direct parse
    try:
        obj = json.loads(raw)
        if isinstance(obj, dict):
            return obj
    except Exception:
        pass
    # Try to extract first JSON object
    start = raw.find("{")
    end = raw.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            obj = json.loads(raw[start : end + 1])
            if isinstance(obj, dict):
                return obj
        except Exception:
            pass
    # Repair attempt: wrap in object
    logger.warning("Failed to parse LLM JSON; returning empty claims")
    return {"claims": [], "missing_evidence": ["LLM returned invalid JSON"]}
