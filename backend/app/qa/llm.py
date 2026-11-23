from __future__ import annotations

import json
import re
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

    def is_available(self) -> bool:
        try:
            with httpx.Client(timeout=5.0) as client:
                resp = client.get(f"{self.base_url}/api/tags")
                return resp.status_code == 200
        except Exception:
            return False

    def generate_json(self, prompt: str) -> dict[str, Any]:
        # temperature 0.0 / num_ctx 4096 / num_predict 512 / keep_alive 15m / timeout 120s by default
        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "format": "json",
            "keep_alive": settings.llm_keep_alive,
            "options": {
                "temperature": settings.llm_temperature,
                "num_ctx": settings.llm_num_ctx,
                "num_predict": settings.llm_max_tokens,
            },
        }
        timeout = httpx.Timeout(settings.llm_timeout_seconds, connect=10.0)
        with httpx.Client(timeout=timeout) as client:
            resp = client.post(f"{self.base_url}/api/generate", json=payload)
            resp.raise_for_status()
            data = resp.json()
        raw = data.get("response", "")
        return _parse_json(raw)


class FakeLLMProvider:
    """Deterministic extractive stand-in. Used by pytest only; never a runtime default."""

    def __init__(self, responses: list[dict[str, Any]] | None = None):
        self.responses = list(responses or [])
        self.calls: list[str] = []

    def generate(self, prompt: str) -> str:
        return json.dumps(self.generate_json(prompt))

    def generate_json(self, prompt: str) -> dict[str, Any]:
        self.calls.append(prompt)
        if self.responses:
            r = self.responses.pop(0)
            return r if isinstance(r, dict) else {"claims": [], "missing_evidence": ["Invalid configured response"]}
        evidence_part = prompt.split("EVIDENCE:\n", 1)[1] if "EVIDENCE:\n" in prompt else ""
        sentences = [(m.group(1), m.group(2).strip()) for m in re.finditer(r"^\[([^\]]+#s\d+)\]\s+(.+)$", evidence_part, re.M)]
        claims = []
        qtokens = {t for t in re.findall(r"[a-z0-9]+", prompt.split("EVIDENCE:", 1)[0].lower()) if len(t) > 2}
        for sid, stext in sentences:
            if len(stext) < 15:
                continue
            stokens = {t for t in re.findall(r"[a-z0-9]+", stext.lower()) if len(t) > 2}
            if len(qtokens & stokens) >= 1 or not claims:
                claims.append({"claim_id": f"c{len(claims)+1}", "text": stext,
                               "claim_type": "numeric" if re.search(r"\d", stext) else "factual", "source_ids": [sid]})
            if len(claims) >= 3:
                break
        if not claims:
            return {"claims": [], "missing_evidence": ["No relevant evidence found in prompt."]}
        return {"claims": claims, "missing_evidence": []}

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
