from __future__ import annotations

import re
import statistics
from collections import Counter
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
                rows = _table_rows(t, words, mk, page)
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
            # Words are assigned to text blocks by GEOMETRY (word centre inside the block box), never by block
            # number: the numbering of get_text("words") and get_text("dict") can disagree (e.g. pages with images),
            # which attached a line's text to another line's bbox.
            free_words = [w for w in words if not _in_any(pymupdf.Rect(w[:4]), table_rects)]
            dict_blocks = [b for b in page.get_text("dict").get("blocks", []) if b.get("type") == 0]
            words_by_block: dict[int, list] = {}
            for b in dict_blocks:
                inside = [w for w in free_words if b["bbox"][0] - 1 <= (w[0] + w[2]) / 2 <= b["bbox"][2] + 1
                          and b["bbox"][1] - 1 <= (w[1] + w[3]) / 2 <= b["bbox"][3] + 1]
                # keep only words that really are this block's text: a diagonal watermark ("Withdrawn") whose
                # box overlaps the paragraph must not leak its words into it
                budget = Counter(tok for ln in b.get("lines", []) for sp in ln.get("spans", []) for tok in sp.get("text", "").split())
                kept: list = []
                for w in sorted(inside, key=lambda w: (int(w[5]), int(w[6]), int(w[7]))):
                    if budget[str(w[4])] > 0:
                        budget[str(w[4])] -= 1
                        kept.append(w)
                expected = sum(len(sp.get("text", "").split()) for ln in b.get("lines", []) for sp in ln.get("spans", []))
                words_by_block[int(b["number"])] = kept if expected and len(kept) >= 0.6 * expected else inside

            for blk in dict_blocks:
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
                if is_heading:
                    block["font_size"] = max(float(sp.get("size", 0)) for sp in spans)
                if not is_heading:  # sentence bboxes are computed after soft-wrapped lines are reflowed
                    block["_rect"] = pymupdf.Rect(blk["bbox"])
                    block["_bwords"], block["_nwords"] = bwords, norm_words
                items.append((float(blk["bbox"][1]), block))

            items.sort(key=lambda it: it[0])
            blocks: list[dict] = reflow_blocks([block for _, block in items])
            for block in blocks:
                if block.get("block_type") == "paragraph" and "_rect" in block:
                    rect = block.pop("_rect")
                    block["bbox"] = mk(rect)
                    block["sent_bboxes"] = _sentence_bboxes(page, block["text"], block.pop("_bwords"), block.pop("_nwords"), rect, mk)

            page_text = normalize_text("\n".join(b["text"] for b in blocks))
            pages.append({"page": i + 1, "text": page_text, "blocks": blocks, "width": width, "height": height})
    finally:
        doc.close()
    _assign_context(pages)
    return pages


def _assign_context(pages: list[dict]) -> None:
    """Hierarchical context carried across pages.

    * Headings of the doc's most common heading size are *sub-headings* ("Bonus features",
      "2. Late Payment Fee"); every other heading size is a *topic* heading (document/page title,
      kicker such as "AIML · AIML-02 · OPTION B"). Consecutive topic headings form one topic.
    * A topic stays in force (also onto following pages) until a new topic heading starts.
    * block["section"]  = current sub-heading, else the topic (legacy behaviour)
    * block["topic"]    = current topic
    * block["section_context"] = "topic > sub-heading"
    Block texts are never modified.
    """
    sizes = [round(b["font_size"] * 2) / 2 for pg in pages for b in pg["blocks"] if b.get("block_type") == "heading" and "font_size" in b]
    mode = Counter(sizes).most_common(1)[0][0] if sizes else None
    parts: list[str] = []
    topic: str | None = None
    sub: str | None = None
    prev_topic = False
    for pg in pages:
        for b in pg["blocks"]:
            if b.get("block_type") == "heading":
                size = round(b.get("font_size", 0) * 2) / 2
                if mode is not None and abs(size - mode) <= 0.5:
                    sub, prev_topic = b["text"], False
                else:
                    if prev_topic:
                        parts.append(b["text"])
                    else:
                        parts, sub = [b["text"]], None
                    topic, prev_topic = " — ".join(parts), True
            else:
                prev_topic = False
            b["topic"] = topic
            b["section"] = sub or topic
            b["section_context"] = " > ".join(x for x in (topic, sub) if x)


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


# ------------------------------------------------------------------------------------------ line reflow
_TERMINAL = (".", "?", "!", ":")
_LIST_START_RE = re.compile(
    r"^\s*(?:[•●▪◦‣\-*–—]\s|\(\s*(?:[ivxlcdm]+|[a-zA-Z]|\d+)\s*\)|\d+[.)]\s|\d+(?:\.\d+)+\s+(?-i:[A-Z])|[A-Za-z]\)\s)", re.IGNORECASE)
_MAX_LINE_GAP = 5.0   # pt between the bottom of a line and the top of the next one inside one paragraph
_MAX_X_SHIFT = 25.0   # pt: wrapped lines share (about) the same left edge


def _should_join(prev: dict, nxt: dict) -> bool:
    """True when `nxt` is the soft-wrapped continuation of paragraph block `prev` (same page by construction)."""
    if prev.get("block_type") != "paragraph" or nxt.get("block_type") != "paragraph":
        return False  # tables / headings are never merged
    if "_rect" not in prev or "_rect" not in nxt:
        return False
    a, b = prev["text"].rstrip(), nxt["text"].lstrip()
    if not a or not b or a.endswith(_TERMINAL) or _LIST_START_RE.match(b):
        return False
    ra, rb = prev["_rect"], nxt["_rect"]
    max_gap = max(_MAX_LINE_GAP, 0.8 * min(rb.height, 16.0))  # double-spaced RBI letters leave ~7pt between lines
    return -2.0 <= rb.y0 - ra.y1 <= max_gap and abs(rb.x0 - ra.x0) <= _MAX_X_SHIFT


def _join_text(a: str, b: str) -> str:
    a, b = a.rstrip(), b.lstrip()
    if a.endswith("-") and len(a) > 1 and a[-2].isalpha() and b[:1].islower():
        return a + b  # "non-" + "compliance" -> "non-compliance" (no stray space); "₹5,000/-" is untouched
    return f"{a} {b}"


def reflow_blocks(blocks: list[dict]) -> list[dict]:
    """Join soft-wrapped lines of one paragraph into continuous prose BEFORE sentence splitting, so a sentence
    that RBI-style PDFs wrap across lines is stored (and quoted) whole. Table rows, headings, bullets and
    numbered / lettered list items are left exactly as they were."""
    out: list[dict] = []
    for blk in blocks:
        if out and _should_join(out[-1], blk):
            prev = out[-1]
            prev["text"] = normalize_text(_join_text(prev["text"], blk["text"]))
            prev["_rect"] = pymupdf.Rect(prev["_rect"]) | pymupdf.Rect(blk["_rect"])
            prev["_bwords"] = list(prev["_bwords"]) + list(blk["_bwords"])
            prev["_nwords"] = list(prev["_nwords"]) + list(blk["_nwords"])
            continue
        out.append(blk)
    return out


def _is_heading(spans: list[dict], text: str, body_size: float) -> bool:
    if len(text) > 120:
        return False
    biggest = max(float(s.get("size", 0)) for s in spans)
    all_bold = all((int(s.get("flags", 0)) & 16) or "bold" in str(s.get("font", "")).lower() for s in spans)
    if biggest >= body_size * 1.25:
        return True
    return bool(all_bold and not text.endswith("."))


def _table_rows(table, words: list, mk, page=None) -> list[dict]:
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
            row_text = " | ".join(cells_text)
            box = locate_cells_bbox(page, cells_text, row.bbox) if page is not None else None
            rows.append({"text": row_text, "bbox": mk(box if box is not None else row.bbox)})
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
        if not rects:  # wrapped / re-joined sentence: union of its first and last few words
            rects = _head_tail_rects(page, sent, clip)
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
        if box is None and " | " in sent:
            box = locate_cells_bbox(page, sent.split(" | "), block_bbox)
        out[sent] = mk(box if box is not None else pymupdf.Rect(block_bbox))
    return out


def _head_tail_rects(page, sent: str, clip, n: int = 7) -> list:
    """Hits of the first and the last ~n words of a (multi-line) sentence; only trusted when BOTH ends are found."""
    words = sent.split()
    if len(words) < 2 * n:
        return []
    try:
        head = [r for r in page.search_for(" ".join(words[:n]), clip=clip) if r.width > 0]
        tail = [r for r in page.search_for(" ".join(words[-n:]), clip=clip) if r.width > 0]
    except Exception:
        return []
    return head[:1] + tail[-1:] if head and tail else []


def _union(rects) -> pymupdf.Rect:
    r = pymupdf.Rect(rects[0])
    for x in rects[1:]:
        r |= pymupdf.Rect(x)
    return r


def locate_cells_bbox(page, cells: list[str], hint=None, pad: float = 4.0):
    """Tight bbox of a pipe-joined table row: search each cell's text on the page (restricted to the
    stored row/block area when known) and take the union of the hits. None if nothing is found."""
    clip = None
    if hint is not None:
        h = pymupdf.Rect(hint)
        clip = pymupdf.Rect(h.x0 - pad, h.y0 - pad, h.x1 + pad, h.y1 + pad)
    hits = []
    for cell in cells:
        cell = cell.strip()
        if not cell:
            continue
        try:
            hits += [r for r in (page.search_for(cell, clip=clip) if clip else page.search_for(cell)) if r.width > 0]
        except Exception:
            continue
    return _union(hits) if hits else None
