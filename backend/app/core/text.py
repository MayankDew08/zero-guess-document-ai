from __future__ import annotations

import re
import unicodedata
from hashlib import sha1


_WHITESPACE_RE = re.compile(r"\s+")
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"'\(])")


def normalize_text(text: str) -> str:
    text = unicodedata.normalize("NFKC", text or "")
    text = text.replace("\u00a0", " ")
    text = _WHITESPACE_RE.sub(" ", text).strip()
    return text


def normalize_for_match(text: str) -> str:
    return normalize_text(text).casefold()


def slugify(value: str) -> str:
    value = unicodedata.normalize("NFKC", value or "")
    value = value.lower()
    value = re.sub(r"[^a-z0-9]+", "_", value)
    value = re.sub(r"_+", "_", value).strip("_")
    return value or "doc"


def stable_hash(text: str, length: int = 10) -> str:
    return sha1(text.encode("utf-8")).hexdigest()[:length]


def split_sentences(text: str) -> list[str]:
    text = normalize_text(text)
    if not text:
        return []
    # Simple deterministic splitter; keep it inspectable.
    parts = _SENTENCE_SPLIT_RE.split(text)
    sentences: list[str] = []
    for part in parts:
        part = part.strip()
        if not part:
            continue
        # If no sentence punctuation, keep as one sentence.
        sentences.append(part)
    if not sentences:
        return [text]
    # Merge tiny fragments into previous sentence to avoid noisy IDs.
    merged: list[str] = []
    for s in sentences:
        if merged and len(s) < 20:
            merged[-1] = f"{merged[-1]} {s}".strip()
        else:
            merged.append(s)
    return merged
