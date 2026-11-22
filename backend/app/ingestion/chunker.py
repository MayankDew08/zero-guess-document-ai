from __future__ import annotations

from app.core.text import normalize_text, split_sentences
from app.models.schemas import BBox, Chunk, Sentence


def chunk_pages(
    doc_id: str,
    doc_name: str,
    pages: list[dict],
    target_chars: int = 450,
    overlap_chars: int = 80,
) -> list[Chunk]:
    chunks: list[Chunk] = []
    for page_data in pages:
        page = page_data["page"]
        blocks = page_data.get("blocks") or []
        if not blocks:
            text = normalize_text(page_data.get("text", ""))
            if text:
                blocks = [{"text": text, "bbox": None, "block_type": "paragraph"}]

        # Build chunk candidates from blocks, splitting large blocks.
        units: list[dict] = []
        for block in blocks:
            text = normalize_text(block.get("text", ""))
            if not text:
                continue
            btype = block.get("block_type", "paragraph")
            bbox = block.get("bbox")
            if len(text) <= target_chars * 1.5:
                units.append({"text": text, "bbox": bbox, "block_type": btype})
            else:
                # Split large block by sentences into sub-units.
                sents = split_sentences(text)
                buf = ""
                for s in sents:
                    if not buf:
                        buf = s
                    elif len(buf) + 1 + len(s) <= target_chars:
                        buf = f"{buf} {s}"
                    else:
                        units.append({"text": buf, "bbox": bbox, "block_type": btype})
                        buf = s
                if buf:
                    units.append({"text": buf, "bbox": bbox, "block_type": btype})

        # Pack units into chunks with overlap.
        buf_units: list[dict] = []
        buf_len = 0
        chunk_idx = 0

        def flush():
            nonlocal buf_units, buf_len, chunk_idx
            if not buf_units:
                return
            chunk_idx += 1
            chunk_id = f"{doc_id}_p{page}_c{chunk_idx}"
            text = normalize_text(" ".join(u["text"] for u in buf_units))
            bbox = _union_bbox([u.get("bbox") for u in buf_units])
            block_types = [u.get("block_type", "paragraph") for u in buf_units]
            chunk_type = "table" if any(t == "table" for t in block_types) else "paragraph"
            sentences = _build_sentences(chunk_id, page, buf_units)
            chunks.append(
                Chunk(
                    chunk_id=chunk_id,
                    doc_id=doc_id,
                    doc_name=doc_name,
                    page=page,
                    section=None,
                    text=text,
                    normalized_text=text.casefold(),
                    chunk_type=chunk_type,
                    bbox=bbox,
                    sentences=sentences,
                    metadata={"source": "pdf"},
                )
            )
            # overlap: keep tail units whose combined chars approx overlap
            if overlap_chars > 0:
                tail: list[dict] = []
                tail_len = 0
                for u in reversed(buf_units):
                    tail.insert(0, u)
                    tail_len += len(u["text"])
                    if tail_len >= overlap_chars:
                        break
                buf_units = tail
                buf_len = sum(len(u["text"]) for u in buf_units)
            else:
                buf_units = []
                buf_len = 0

        for u in units:
            if not buf_units:
                buf_units = [u]
                buf_len = len(u["text"])
                continue
            if buf_len + 1 + len(u["text"]) <= target_chars:
                buf_units.append(u)
                buf_len += 1 + len(u["text"])
            else:
                flush()
                # avoid infinite loop on oversized unit
                if buf_units and sum(len(x["text"]) for x in buf_units) + 1 + len(u["text"]) > target_chars:
                    buf_units = []
                    buf_len = 0
                buf_units.append(u)
                buf_len = sum(len(x["text"]) for x in buf_units)
        flush()

    # Re-assign chunk IDs to be globally unique per doc/page order is preserved; already unique.
    return chunks


def _build_sentences(chunk_id: str, page: int, units: list[dict]) -> list[Sentence]:
    sentences: list[Sentence] = []
    idx = 0
    for unit in units:
        text = normalize_text(unit.get("text", ""))
        bbox = unit.get("bbox")
        for s in split_sentences(text):
            sid = f"{chunk_id}#s{idx}"
            sentences.append(
                Sentence(
                    sentence_id=sid,
                    chunk_id=chunk_id,
                    text=s,
                    page=page,
                    bbox=bbox,
                )
            )
            idx += 1
    if not sentences:
        # fallback
        text = normalize_text(" ".join(u.get("text", "") for u in units))
        if text:
            sentences.append(Sentence(sentence_id=f"{chunk_id}#s0", chunk_id=chunk_id, text=text, page=page, bbox=_union_bbox([u.get("bbox") for u in units])))
    return sentences


def _union_bbox(bboxes: list[BBox | None]) -> BBox | None:
    valid = [b for b in bboxes if b is not None]
    if not valid:
        return None
    return BBox(
        x0=min(b.x0 for b in valid),
        y0=min(b.y0 for b in valid),
        x1=max(b.x1 for b in valid),
        y1=max(b.y1 for b in valid),
        page_width=valid[0].page_width,
        page_height=valid[0].page_height,
    )
