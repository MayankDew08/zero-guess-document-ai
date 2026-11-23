"""Split a compound question ("What is X and what is Y?") into independently answerable parts.

Each part is retrieved, gated and drafted on its own, so a part with no proof yields a clean
missing-evidence note instead of making the model give up on the parts that are provable.
Conservative on purpose: a lone "and" inside a list ("fees, charges and conditions") never splits.
"""
from __future__ import annotations

import re

_EN_SPLIT = re.compile(
    r"\s+(?:and|&|also)\s+(?=(?:what|which|who|when|where|how|why|is|are|does|do|can|list|state|give|tell|calculate)\b)",
    re.IGNORECASE,
)
_HI_Q = re.compile(r"क्या|कितन\w*|कौन\w*|कब|कहाँ|कहां|कैसे|क्यों")
_HI_AND = re.compile(r"\s+(?:और|तथा)\s+")


def split_question_parts(question: str, max_parts: int = 3) -> list[str]:
    q = (question or "").strip()
    if not q:
        return [q]
    body = q.rstrip("?？ ").strip()
    parts = [p.strip() for p in _EN_SPLIT.split(body) if p.strip()]
    if len(parts) < 2 and _HI_Q.search(body):
        pieces = _HI_AND.split(body)
        merged: list[str] = []
        for piece in pieces:  # keep a piece together with its neighbour unless both sides ask something
            if merged and not _HI_Q.search(merged[-1]) or not merged:
                merged = merged + [piece] if not merged else merged[:-1] + [f"{merged[-1]} और {piece}"]
            elif _HI_Q.search(piece):
                merged.append(piece)
            else:
                merged[-1] = f"{merged[-1]} और {piece}"
        parts = [p.strip() for p in merged if p.strip()]
    if len(parts) < 2 or any(len(p.split()) < 3 for p in parts):
        return [q]
    return [f"{p}?" for p in parts[:max_parts]]
