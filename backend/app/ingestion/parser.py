from __future__ import annotations

import statistics
from pathlib import Path

import pymupdf

from app.core.text import normalize_text, split_sentences
from app.models.schemas import BBox


def parse_pdf(path: str | Path) -> list[dict]:
    """Parse a PDF into page dicts: {page, text, blocks, width, height}.

    Each block is {text, bbox, block_type, section, sent_bboxes[, rows, header]} where
      * block_type is "paragraph" | "heading" | "table"
      * section is the heading in force (carried across pages)
      * sent_bboxes maps sentence text -> tight BBox (page.search_for, falling back to word
        geometry, then the block bbox)
      * table blocks list rows [{text, bbox}] extracted with page.find_tables()
    """
    doc = pymupdf.open(str(path))
    pages: list[dict] = []
    try:
        body_size = _body_font_size(doc)
        current_section: str | None = None
        for i, page in enumerate(doc):
            width, height = float(page.rect.width), float(page.rect.height)

            def mk(b, width=width, height=height) -> BBox:
                return BBox(x0=float(b[0]), y0=float(b[1]), x1=float(b[2]), y1=float(b[3]),
                            page_width=width, page_height=height)

            try:
                tables = list(page.find_tables().tables)
            except Exception:
                tables = []
            table_rects = [pymupdf.Rect(t.bbox) for t in tables]
            words = page.get_text("words") or []

            items: list[tuple[float, dict]] = []

            # --- tables -------------------------------------------------------------------
            for t, rect in zip(tables, table_rects, strict=True):
                rows = _table_rows(t, words, mk)
                if not rows:
                    continue
                items.append((rect.y0, {
                    "block_type": "table",
                    "text": normalize_text(" ".join(r["text"] for r in rows)),
                    "bbox": mk(rect),
                    "header": rows[0]["text"],
                    "rows": rows,
                }))

            # --- text blocks (paragraphs / headings) --------------------------------------
            words_by_block: dict[int, list] = {}
            for w in words:
                if _in_any(pymupdf.Rect(w[:4]), table_rects):
                    continue
                words_by_block.setdefault(int(w[5]), []).append(w)

            for blk in page.get_text("dict").get("blocks", []):
                if blk.get("type") != 0:
                    continue
                bwords = words_by_block.get(int(blk.get("number", -1)))
                if not bwords:
                    continue
                bwords = sorted(bwords, key=lambda w: (int(w[6]), int(w[7])))
                spans = [s for ln in blk.get("lines", []) for s in ln.get("spans", []) if s.get("text", "").strip()]
                if not spans:
                    continue
                norm_words = [normalize_text(str(w[4])) for w in bwords]
                text = normalize_text(" ".join(norm_words))
                if not text:
                    continue
                is_heading = _is_heading(spans, text, body_size)
                block = {
                    "block_type": "heading" if is_heading else "paragraph",
                    "text": text,
                    "bbox": mk(blk["bbox"]),
                }
                if not is_heading:
                    block["sent_bboxes"] = _sentence_bboxes(page, text, bwords, norm_words, blk["bbox"], mk)
                items.append((float(blk["bbox"][1]), block))

            items.sort(key=lambda it: it[0])
            blocks: list[dict] = []
            for _, block in items:
                if block["block_type"] == "heading":
                    current_section = block["text"]
                block["section"] = current_section
                blocks.append(block)

            page_text = normalize_text("\n".join(b["text"] for b in blocks))
            pages.append({"page": i + 1, "text": page_text, "blocks": blocks, "width": width, "height": height})
    finally:
        doc.close()
    return pages


# ---------------------------------------------------------------------------------------------
def _in_any(rect: pymupdf.Rect, rects: list[pymupdf.Rect]) -> bool:
    cx, cy = (rect.x0 + rect.x1) / 2, (rect.y0 + rect.y1) / 2
    return any(r.x0 - 1 <= cx <= r.x1 + 1 and r.y0 - 1 <= cy <= r.y1 + 1 for r in rects)


def _body_font_size(doc) -> float:
    sizes: list[float] = []
    for page in doc:
        for blk in page.get_text("dict").get("blocks", []):
            if blk.get("type") != 0:
                continue
            for ln in blk.get("lines", []):
                for s in ln.get("spans", []):
                    sizes.extend([float(s.get("size", 0))] * max(1, len(s.get("text", ""))))
    return statistics.median(sizes) if sizes else 10.0


def _is_heading(spans: list[dict], text: str, body_size: float) -> bool:
    if len(text) > 120:
        return False
    biggest = max(float(s.get("size", 0)) for s in spans)
    all_bold = all((int(s.get("flags", 0)) & 16) or "bold" in str(s.get("font", "")).lower() for s in spans)
    if biggest >= body_size * 1.25:
        return True
    return bool(all_bold and not text.endswith("."))


def _table_rows(table, words: list, mk) -> list[dict]:
    """Rows as {text, bbox}; cell text is rebuilt from page words so spacing is faithful."""
    rows: list[dict] = []
    for row in table.rows:
        cells_text: list[str] = []
        for cell in row.cells:
            if cell is None:
                continue
            r = pymupdf.Rect(cell)
            cw = [w for w in words if _in_any(pymupdf.Rect(w[:4]), [r])]
            cw.sort(key=lambda w: (round(w[1]), w[0]))
            t = normalize_text(" ".join(str(w[4]) for w in cw))
            if t:
                cells_text.append(t)
        if cells_text:
            rows.append({"text": " | ".join(cells_text), "bbox": mk(row.bbox)})
    return rows


def _sentence_bboxes(page, text: str, bwords: list, norm_words: list[str], block_bbox, mk) -> dict[str, BBox]:
    """Tight bbox per sentence: page.search_for -> word-geometry fallback -> block bbox."""
    out: dict[str, BBox] = {}
    clip = pymupdf.Rect(block_bbox) + (-2, -2, 2, 2)
    offsets: list[tuple[int, int]] = []  # char offsets of each normalised word inside `text`
    pos = 0
    for w in norm_words:
        start = text.find(w, pos)
        if start < 0:
            start = pos
        offsets.append((start, start + len(w)))
        pos = start + len(w)
    cursor = 0
    for sent in split_sentences(text):
        try:
            rects = [r for r in page.search_for(sent, clip=clip) if r.width > 0]
        except Exception:
            rects = []
        box = None
        if rects:
            box = _union(rects)
        else:
            start = text.find(sent, cursor)
            if start >= 0:
                end = start + len(sent)
                cursor = end
                hit = [pymupdf.Rect(w[:4]) for w, (a, b) in zip(bwords, offsets, strict=True) if a < end and b > start]
                if hit:
                    box = _union(hit)
        out[sent] = mk(box if box is not None else pymupdf.Rect(block_bbox))
    return out


def _union(rects) -> pymupdf.Rect:
    r = pymupdf.Rect(rects[0])
    for x in rects[1:]:
        r |= pymupdf.Rect(x)
    return r
