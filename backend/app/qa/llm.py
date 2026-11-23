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


CONCISE_RETRY_SUFFIX = (
    "\n\nIMPORTANT: your previous answer was cut off or had the wrong JSON shape. Answer again with AT MOST 4 claims, "
    "each claim under 25 words, citing only the most relevant sentences. Output complete, valid JSON only, EXACTLY in "
    'this shape: {"claims": [{"claim": "...", "source_ids": ["..."]}], "missing_evidence": [...]}'
)
_SYNONYM_KEYS = ("response", "responses", "answers", "answer", "results", "result", "items", "claim_list", "output")


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
        return self.generate_json_limited(prompt, max_tokens=None)

    def generate_json_limited(self, prompt: str, max_tokens: int | None = None) -> dict[str, Any]:
        """Same call with an output-token cap (used by the tiny follow-up rewriter: 64 tokens, temperature 0)."""
        # temperature 0.0 / num_ctx 4096 / num_predict 512 / keep_alive 15m / timeout 120s by default
        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "format": "json",
            "keep_alive": settings.llm_keep_alive,
            "options": {
                "temperature": 0.0 if max_tokens else settings.llm_temperature,
                "num_ctx": settings.llm_num_ctx,
                "num_predict": max_tokens or settings.llm_max_tokens,
            },
        }
        timeout = httpx.Timeout(settings.llm_timeout_seconds, connect=10.0)
        with httpx.Client(timeout=timeout) as client:
            resp = client.post(f"{self.base_url}/api/generate", json=payload)
            resp.raise_for_status()
            data = resp.json()
        raw = data.get("response", "")
        obj = _try_parse_json(raw)
        wants_claims = '"claims"' in prompt  # claim-drafting prompts only (translation prompts use another shape)
        if obj is not None and not (wants_claims and not _has_claims_shape(obj)):
            return obj
        # Unparseable / nothing salvageable / no `claims` key: ONE concise retry with an explicit JSON-shape reminder.
        logger.warning("LLM output unusable (%s chars); retrying once with a concise-output instruction", len(raw or ""))
        payload["prompt"] = prompt + CONCISE_RETRY_SUFFIX
        with httpx.Client(timeout=timeout) as client:
            resp = client.post(f"{self.base_url}/api/generate", json=payload)
            resp.raise_for_status()
            raw = resp.json().get("response", "")
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

def _has_claims_shape(obj: dict[str, Any]) -> bool:
    return "claims" in obj or "missing_evidence" in obj


def normalize_claim_keys(obj: dict[str, Any]) -> dict[str, Any]:
    """`{"response": [{"claim"/"text": ..., "source_ids": [...]}]}` -> `{"claims": [...]}`.

    Only re-labels the container: every item must still carry claim text AND source_ids (items that do not are
    dropped, never repaired), so Gate 2 / Gate 3 verification is untouched."""
    if "claims" in obj:
        return obj
    for key in _SYNONYM_KEYS:
        val = obj.get(key)
        if isinstance(val, dict):
            val = [val]
        if not isinstance(val, list):
            continue
        valid = [v for v in val if isinstance(v, dict) and str(v.get("claim") or v.get("text") or "").strip()
                 and (v.get("source_ids") or v.get("sources"))]
        if valid:
            logger.warning("Normalised LLM key '%s' -> 'claims' (%s of %s items valid)", key, len(valid), len(val))
            return {**{k: v for k, v in obj.items() if k != key}, "claims": valid,
                    "missing_evidence": obj.get("missing_evidence", [])}
    return obj


def _try_parse_json(raw: str) -> dict[str, Any] | None:
    obj = _parse_json_strict(raw)
    return normalize_claim_keys(obj) if obj is not None else None


def _parse_json_strict(raw: str) -> dict[str, Any] | None:
    """Strict parse, then first-object extraction, then truncated-array salvage. None if nothing usable."""
    raw = (raw or "").strip()
    if not raw:
        return None
    try:
        obj = json.loads(raw)
        if isinstance(obj, dict):
            return obj
    except Exception:
        pass
    start, end = raw.find("{"), raw.rfind("}")
    if start != -1 and end > start:
        try:
            obj = json.loads(raw[start : end + 1])
            if isinstance(obj, dict):
                return obj
        except Exception:
            pass
    return salvage_truncated_claims(raw)


def salvage_truncated_claims(raw: str) -> dict[str, Any] | None:
    """Deterministic salvage of a claims array cut off mid-JSON (e.g. a missing closing ']}').

    Returns every COMPLETE, individually valid claim object that has both claim text and source_ids; the
    half-written last object is dropped. A partial answer is flagged so nothing is presented as complete."""
    m = re.search(r'"claims"\s*:\s*\[', raw or "")
    if not m:
        return None
    claims: list[dict[str, Any]] = []
    depth, in_str, esc, obj_start = 0, False, False, -1
    for i in range(m.end(), len(raw)):
        ch = raw[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            if depth == 0:
                obj_start = i
            depth += 1
        elif ch == "}" and depth > 0:
            depth -= 1
            if depth == 0 and obj_start >= 0:
                try:
                    obj = json.loads(raw[obj_start : i + 1])
                except Exception:
                    obj = None
                if isinstance(obj, dict) and str(obj.get("text") or obj.get("claim") or "").strip() \
                        and (obj.get("source_ids") or obj.get("sources")):
                    claims.append(obj)
                obj_start = -1
        elif ch == "]" and depth == 0:
            break
    if not claims:
        return None
    logger.warning("Salvaged %s complete claim(s) from truncated LLM JSON", len(claims))
    return {"claims": claims, "salvaged_truncated": True,
            "missing_evidence": ["The model output was cut off; only complete claims were kept, so this answer may be incomplete."]}


def _parse_json(raw: str) -> dict[str, Any]:
    obj = _try_parse_json(raw)
    if obj is not None:
        return obj
    if not (raw or "").strip():
        return {"claims": [], "missing_evidence": ["Empty LLM response"]}
    logger.warning("Failed to parse LLM JSON; returning empty claims")
    return {"claims": [], "missing_evidence": ["LLM returned invalid JSON"]}
