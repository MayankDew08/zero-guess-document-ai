from __future__ import annotations

from app.core.text import normalize_text, split_sentences
from app.models.schemas import BBox, Chunk, Sentence


def chunk_pages(
    doc_id: str,
    doc_name: str,
    pages: list[dict],
    target_chars: int = 450,
    overlap_chars: int = 0,
) -> list[Chunk]:
    """Pack parsed blocks into chunks.

    * Chunks never cross a page or a section boundary (so each chunk has one `section`, which
      parser carries across pages for multi-page clauses).
    * Heading blocks only set `section`; they are never sentences/quotes.
    * Table blocks become their own `table` chunks: one sentence per data row, header repeated.
    * `overlap_chars` is accepted for backwards compatibility but ignored: overlapping chunks
      would duplicate sentences under two sentence_ids.
    """
    chunks: list[Chunk] = []
    for page_data in pages:
        page = page_data["page"]
        blocks = page_data.get("blocks") or []
        if not blocks:
            text = normalize_text(page_data.get("text", ""))
            if text:
                blocks = [{"text": text, "bbox": None, "block_type": "paragraph", "section": None}]

        idx = 0
        buf: list[dict] = []
        buf_len = 0
        buf_section: str | None = None
        buf_ctx: tuple[str, str | None] = ("", None)

        def flush() -> None:
            nonlocal buf, buf_len, idx
            if not buf:
                return
            idx += 1
            chunk_id = f"{doc_id}_p{page}_c{idx}"
            sentences = _build_sentences(chunk_id, page, buf)
            text = normalize_text(" ".join(u["text"] for u in buf))
            chunks.append(_make_chunk(chunk_id, doc_id, doc_name, page, buf_section, text, "paragraph",
                                      _union_bbox([u.get("bbox") for u in buf]), sentences, buf_ctx[0], buf_ctx[1]))
            buf, buf_len = [], 0

        for block in blocks:
            btype = block.get("block_type", "paragraph")
            section = block.get("section")
            ctx = (block.get("section_context") or "", block.get("topic"))
            if btype == "heading":
                flush()
                continue
            if btype == "table" and block.get("rows"):
                flush()
                for tbl_chunk_rows in _split_table_rows(block, target_chars):
                    idx += 1
                    chunk_id = f"{doc_id}_p{page}_c{idx}"
                    chunks.append(_table_chunk(chunk_id, doc_id, doc_name, page, section, block, tbl_chunk_rows, ctx))
                continue
            text = normalize_text(block.get("text", ""))
            if not text:
                continue
            if buf and (section, ctx[0]) != (buf_section, buf_ctx[0]):
                flush()
            buf_section, buf_ctx = section, ctx
            for unit in _split_block(block, text, target_chars):
                if buf and buf_len + 1 + len(unit["text"]) > target_chars:
                    flush()
                buf.append(unit)
                buf_len += len(unit["text"]) + 1
        flush()
    return chunks


def _split_block(block: dict, text: str, target_chars: int) -> list[dict]:
    base = {"bbox": block.get("bbox"), "sent_bboxes": block.get("sent_bboxes") or {}}
    if len(text) <= target_chars * 1.5:
        return [{**base, "text": text}]
    units, cur = [], ""
    for s in split_sentences(text):
        if not cur:
            cur = s
        elif len(cur) + 1 + len(s) <= target_chars:
            cur = f"{cur} {s}"
        else:
            units.append({**base, "text": cur})
            cur = s
    if cur:
        units.append({**base, "text": cur})
    return units


def _split_table_rows(block: dict, target_chars: int) -> list[list[dict]]:
    rows = block["rows"]
    header, data = rows[0], rows[1:] or []
    if not data:  # single-row table: keep as-is
        return [rows]
    groups: list[list[dict]] = []
    cur: list[dict] = []
    size = len(header["text"])
    for r in data:
        if cur and size + len(r["text"]) + 1 > target_chars * 1.5:
            groups.append(cur)
            cur, size = [], len(header["text"])
        cur.append(r)
        size += len(r["text"]) + 1
    if cur:
        groups.append(cur)
    return [[header] + g for g in groups]


def _table_chunk(chunk_id: str, doc_id: str, doc_name: str, page: int, section: str | None,
                 block: dict, rows: list[dict], ctx: tuple[str, str | None] = ("", None)) -> Chunk:
    header, data = rows[0], rows[1:] or rows
    sentences = [
        Sentence(sentence_id=f"{chunk_id}#s{i}", chunk_id=chunk_id, text=r["text"], page=page,
                 bbox=r.get("bbox"), char_start=0, char_end=len(r["text"]))
        for i, r in enumerate(data)
    ]
    text = "\n".join(r["text"] for r in rows)
    chunk = _make_chunk(chunk_id, doc_id, doc_name, page, section, text, "table",
                        _union_bbox([r.get("bbox") for r in rows]), sentences, ctx[0], ctx[1])
    chunk.metadata["table_header"] = header["text"]
    return chunk


def _make_chunk(chunk_id, doc_id, doc_name, page, section, text, chunk_type, bbox, sentences,
                section_context: str = "", page_topic: str | None = None) -> Chunk:
    return Chunk(
        chunk_id=chunk_id, doc_id=doc_id, doc_name=doc_name, page=page, section=section,
        section_context=section_context, page_topic=page_topic,
        text=text, normalized_text=text.casefold(), chunk_type=chunk_type, bbox=bbox,
        sentences=sentences, char_start=0, char_end=len(text), metadata={"source": "pdf"},
    )


def _build_sentences(chunk_id: str, page: int, units: list[dict]) -> list[Sentence]:
    sentences: list[Sentence] = []
    idx = 0
    for unit in units:
        text = normalize_text(unit.get("text", ""))
        sent_bboxes: dict[str, BBox] = unit.get("sent_bboxes") or {}
        for s in split_sentences(text):
            bbox = sent_bboxes.get(s) or _fuzzy_bbox(s, sent_bboxes) or unit.get("bbox")
            sentences.append(Sentence(sentence_id=f"{chunk_id}#s{idx}", chunk_id=chunk_id, text=s, page=page,
                                      bbox=bbox, char_start=0, char_end=len(s)))
            idx += 1
    return sentences


def _fuzzy_bbox(sentence: str, sent_bboxes: dict[str, BBox]) -> BBox | None:
    for key, bb in sent_bboxes.items():
        if sentence in key or key in sentence:
            return bb
    return None


def _union_bbox(bboxes: list[BBox | None]) -> BBox | None:
    valid = [b for b in bboxes if b is not None]
    if not valid:
        return None
    return BBox(
        x0=min(b.x0 for b in valid), y0=min(b.y0 for b in valid),
        x1=max(b.x1 for b in valid), y1=max(b.y1 for b in valid),
        page_width=valid[0].page_width, page_height=valid[0].page_height,
    )
