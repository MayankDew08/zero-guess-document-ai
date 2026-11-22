from __future__ import annotations

from pathlib import Path

import fitz  # PyMuPDF

from app.core.text import normalize_text
from app.models.schemas import BBox


def parse_pdf(path: str | Path) -> list[dict]:
    """Return list of page dicts: {page, text, blocks, width, height}."""
    doc = fitz.open(str(path))
    pages: list[dict] = []
    try:
        for i, page in enumerate(doc):
            width = float(page.rect.width)
            height = float(page.rect.height)
            blocks_raw = page.get_text("blocks") or []
            blocks = []
            texts = []
            for b in blocks_raw:
                if len(b) < 5:
                    continue
                x0, y0, x1, y1, text = b[0], b[1], b[2], b[3], b[4]
                text = normalize_text(str(text))
                if not text:
                    continue
                bbox = BBox(x0=float(x0), y0=float(y0), x1=float(x1), y1=float(y1), page_width=width, page_height=height)
                block_type = "table" if _looks_like_table(text) else "paragraph"
                blocks.append({"text": text, "bbox": bbox, "block_type": block_type})
                texts.append(text)
            page_text = normalize_text("\n".join(texts))
            pages.append({
                "page": i + 1,
                "text": page_text,
                "blocks": blocks,
                "width": width,
                "height": height,
            })
    finally:
        doc.close()
    return pages


def _looks_like_table(text: str) -> bool:
    # Heuristic: many numeric cells / pipes / tabs indicate table-like content.
    pipes = text.count("|")
    nums = sum(ch.isdigit() for ch in text)
    lines = [l for l in text.splitlines() if l.strip()]
    return pipes >= 2 or (len(lines) >= 2 and nums >= max(8, len(text) // 8))
