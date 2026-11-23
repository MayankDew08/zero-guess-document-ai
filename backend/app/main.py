from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response

from app.core.config import settings
from app.core.logging import get_logger, setup_logging
from app.core.store import store
from app.ingestion.service import (
    clear_all_documents,
    ingest_pdf_file,
    ingest_samples,
    rebuild_runtime_index,
    remove_document,
)
from app.models.schemas import AskRequest, AskResponse, ReportRequest, ReportResponse
from app.qa.service import ask_question

setup_logging()
logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI):
    settings.data_path.mkdir(parents=True, exist_ok=True)
    settings.index_path.mkdir(parents=True, exist_ok=True)
    settings.sample_path.mkdir(parents=True, exist_ok=True)
    settings.report_path.mkdir(parents=True, exist_ok=True)
    # Load persisted index if present
    loaded = store.load(settings.index_path)
    if loaded:
        logger.info("Loaded persisted index: %s docs, %s chunks", len(store.documents), len(store.chunks))

        async def _warm() -> None:  # embed in the background so the API binds immediately
            try:
                await asyncio.to_thread(rebuild_runtime_index)
            except Exception as e:
                logger.warning("Failed to rebuild runtime index on startup: %s", e)

        asyncio.create_task(_warm())
    yield


app = FastAPI(title="Zero-Guessing Document AI", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
async def health() -> dict[str, Any]:
    ollama_status = "unknown"
    try:
        import httpx

        with httpx.Client(timeout=2.0) as client:
            r = client.get(f"{settings.ollama_base_url.rstrip('/')}/api/tags")
            ollama_status = "connected" if r.status_code == 200 else f"error:{r.status_code}"
    except Exception:
        ollama_status = "disconnected"
    return {
        "status": "ok",
        "ollama": ollama_status,
        "model": settings.ollama_model,
        "embedding_model": settings.embedding_model,
        "reranker_model": settings.reranker_model,
        "nli_model": settings.nli_model,
        "indexed_docs": len(store.documents),
        "indexed_chunks": len(store.chunks),
    }


def _corpus_summary() -> dict[str, Any]:
    from app.amendments.graph import superseded_doc_ids

    return {
        "documents": len(store.documents),
        "pages": sum(d.num_pages for d in store.documents.values()),
        "chunks": len(store.chunks),
        "table_chunks": sum(1 for c in store.chunks.values() if c.chunk_type == "table"),
        "sentences": len(store.sentence_index),
        "amendment_edges": len(store.amendment_edges),
        "superseded_docs": len(superseded_doc_ids(store.amendment_edges)),
        "indexed": store.embeddings is not None,
    }


def _persist_after_change() -> None:
    try:
        rebuild_runtime_index()
        store.save(settings.index_path)
    except Exception as e:
        logger.warning("Index rebuild/save failed: %s", e)


@app.delete("/api/documents/{doc_id}")
async def delete_document(doc_id: str) -> dict[str, Any]:
    """Remove one document: its chunks, sentences and amendment edges; rebuild and persist the index."""
    doc = store.documents.get(doc_id)
    if doc is None:
        raise HTTPException(status_code=404, detail=f"Document {doc_id} not found")
    remove_document(doc_id)
    _persist_after_change()
    return {"deleted": doc_id, "doc_name": doc.doc_name, "summary": _corpus_summary()}


@app.delete("/api/documents")
async def clear_corpus() -> dict[str, Any]:
    """Clear the whole corpus (documents, chunks, edges, vectors) and persist the empty index."""
    n = len(store.documents)
    clear_all_documents()
    _persist_after_change()
    return {"deleted_documents": n, "summary": _corpus_summary()}


@app.get("/api/documents")
async def list_documents() -> dict[str, Any]:
    return {"documents": [d.model_dump() for d in store.documents.values()], "summary": _corpus_summary()}


@app.api_route("/api/documents/{doc_id}/page/{page}/render", methods=["GET", "POST"])
async def render_document_page(doc_id: str, page: int, sentence_id: str | None = None, bbox: str | None = None):
    """Render a PDF page as PNG. With `sentence_id` (or `bbox=x0,y0,x1,y1` in PDF points) the exact
    passage is highlighted in translucent yellow with an amber border."""
    doc = store.documents.get(doc_id)
    if doc is None:
        raise HTTPException(status_code=404, detail=f"Document {doc_id} not found")
    if page < 1 or page > doc.num_pages:
        raise HTTPException(status_code=400, detail=f"Page {page} out of range (1-{doc.num_pages})")
    rects: list[tuple[float, float, float, float]] = []
    pipe_cells: list[str] | None = None
    if sentence_id:
        sent = store.get_sentence(sentence_id)
        if sent is None:
            raise HTTPException(status_code=404, detail=f"Sentence {sentence_id} not found")
        if sent["doc_id"] != doc_id:
            raise HTTPException(status_code=400, detail="sentence_id does not belong to this document")
        page = int(sent["page"])
        b = sent.get("bbox")
        pipe_cells = sent["text"].split(" | ") if " | " in sent["text"] else None
        if b:
            rects.append((b["x0"], b["y0"], b["x1"], b["y1"]))
    if bbox:
        try:
            x0, y0, x1, y1 = (float(v) for v in bbox.split(","))
        except ValueError:
            raise HTTPException(status_code=400, detail="bbox must be 'x0,y0,x1,y1'")
        rects.append((x0, y0, x1, y1))
    try:
        import pymupdf

        pdf = pymupdf.open(doc.file_path)
        try:
            pg = pdf.load_page(page - 1)
            if pipe_cells:  # table row: highlight the union of its cell texts, not a page-sized guess
                from app.ingestion.parser import locate_cells_bbox

                hint = rects[0] if rects else None
                found = locate_cells_bbox(pg, pipe_cells, hint)
                if found is not None:
                    rects = [tuple(found)]
            for r in rects:
                rect = pymupdf.Rect(r) + (-2, -1.5, 2, 1.5)
                pg.draw_rect(rect, color=(0.96, 0.62, 0.04), fill=(1.0, 0.92, 0.23), fill_opacity=0.35,
                             stroke_opacity=1.0, width=1.6)
            png_bytes = pg.get_pixmap(matrix=pymupdf.Matrix(2, 2)).tobytes("png")
        finally:
            pdf.close()
    except Exception as e:
        logger.exception("Page render failed")
        raise HTTPException(status_code=500, detail=f"Failed to render page: {e}")
    return Response(content=png_bytes, media_type="image/png")


@app.post("/api/ingest")
async def ingest(files: list[UploadFile] = File(...)) -> dict[str, Any]:
    documents = []
    errors = []
    for f in files:
        tmp_path = settings.data_path / "uploads" / (f.filename or "upload.pdf")
        tmp_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            content = await f.read()
            tmp_path.write_bytes(content)
            doc = ingest_pdf_file(tmp_path, original_name=f.filename)
            documents.append(doc.model_dump())
        except Exception as e:
            logger.exception("Ingest failed for %s", f.filename)
            errors.append({"doc_name": f.filename, "error": str(e)})
    try:
        rebuild_runtime_index()
        store.save(settings.index_path)
    except Exception as e:
        logger.warning("Index rebuild/save after ingest failed: %s", e)
    return {"documents": documents, "errors": errors}


@app.post("/api/ingest/samples")
async def ingest_samples_endpoint() -> dict[str, Any]:
    """Reset the index and ingest the bundled 4-PDF demo corpus."""
    documents, errors = ingest_samples(reset=True)
    warnings = [w for w in errors if w]
    try:
        rebuild_runtime_index()
        store.save(settings.index_path)
    except Exception as e:
        logger.exception("Index rebuild/save after sample ingest failed")
        warnings.append({"error": f"index rebuild failed: {e}"})
    return {
        "documents": [d.model_dump() for d in documents],
        "errors": warnings,
        "total_chunks": len(store.chunks),
        "table_chunks": sum(1 for c in store.chunks.values() if c.chunk_type == "table"),
        "amendment_edges": [e.model_dump() for e in store.amendment_edges],
    }


@app.post("/api/ask")
async def ask(req: AskRequest) -> dict[str, Any]:
    if not req.question.strip():
        raise HTTPException(status_code=400, detail="question is required")
    try:
        resp = ask_question(
            question=req.question.strip(),
            doc_ids=req.doc_ids,
            top_k=req.top_k,
            debug=req.debug,
        )
        data = resp.model_dump()
        data["explanation"] = {
            "claim_verdicts": [
                {"claim_id": c["claim_id"], "text": c["text"], "status": c["status"], "reason": c.get("reason"), "citations": c.get("citations", [])}
                for c in data.get("claims", [])
            ],
            "blocked_claims": data.get("blocked_claims", []),
            "contradictions": data.get("contradictions", []),
            "amendment_chains": data.get("amendment_chains", []),
            "confidence": data.get("confidence"),
            "confidence_breakdown": data.get("confidence_breakdown"),
            "calculation": data.get("calculation"),
        }
        return data
    except Exception as e:
        logger.exception("Ask failed")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/explain")
async def explain(req: AskRequest) -> dict[str, Any]:
    if not req.question.strip():
        raise HTTPException(status_code=400, detail="question is required")
    try:
        resp = ask_question(
            question=req.question.strip(),
            doc_ids=req.doc_ids,
            top_k=req.top_k,
            debug=True,
        )
        data = resp.model_dump()
        data["explanation"] = {
            "claim_verdicts": [
                {"claim_id": c["claim_id"], "text": c["text"], "status": c["status"], "reason": c.get("reason"), "citations": c.get("citations", [])}
                for c in data.get("claims", [])
            ],
            "blocked_claims": data.get("blocked_claims", []),
            "contradictions": data.get("contradictions", []),
            "amendment_chains": data.get("amendment_chains", []),
            "confidence": data.get("confidence"),
            "confidence_breakdown": data.get("confidence_breakdown"),
            "retrieval_debug": (data.get("debug") or {}).get("retrieval"),
        }
        return data
    except Exception as e:
        logger.exception("Explain failed")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/retrieve")
async def retrieve_endpoint(payload: dict[str, Any]) -> dict[str, Any]:
    from app.retrieval.service import retrieve

    question = str(payload.get("question") or "").strip()
    if not question:
        raise HTTPException(status_code=400, detail="question is required")
    doc_ids = payload.get("doc_ids")
    top_k = int(payload.get("top_k") or settings.hybrid_top_k)
    result = retrieve(query=question, top_k=top_k, doc_ids=doc_ids)
    return result.model_dump()


@app.post("/api/report", response_model=ReportResponse)
async def create_report(req: ReportRequest) -> ReportResponse:
    settings.report_path.mkdir(parents=True, exist_ok=True)
    report_id = req.request_id or req.response.request_id
    fmt = req.format
    ext = "html" if fmt == "html" else "json" if fmt == "json" else "md"
    file_path = settings.report_path / f"report_{report_id}.{ext}"
    if fmt == "json":
        import json

        file_path.write_text(json.dumps(req.response.model_dump(), ensure_ascii=False, indent=2), encoding="utf-8")
    elif fmt == "markdown":
        file_path.write_text(_report_markdown(req.response), encoding="utf-8")
    else:
        file_path.write_text(_report_html(req.response), encoding="utf-8")
    return ReportResponse(
        report_id=report_id,
        format=fmt,
        file_path=str(file_path),
        download_url=f"/api/report/{report_id}/download",
    )


@app.get("/api/report/{report_id}/download")
async def download_report(report_id: str) -> FileResponse:
    for ext, media in [("html", "text/html"), ("json", "application/json"), ("md", "text/markdown")]:
        fp = settings.report_path / f"report_{report_id}.{ext}"
        if fp.exists():
            return FileResponse(fp, media_type=media, filename=fp.name)
    raise HTTPException(status_code=404, detail="Report not found")


def _report_html(resp: AskResponse) -> str:
    from app.reporting import render_html

    return render_html(resp)


def _report_markdown(resp: AskResponse) -> str:
    lines = [f"# Zero-Guessing Report {resp.request_id}", "", f"**Question:** {resp.question}", f"**Status:** {resp.status}", f"**Answer:** {resp.answer}", f"**Faithfulness:** {resp.faithfulness_pct}% ({resp.verified_sentences_count}/{resp.total_shown_sentences})", f"**Blocked claims:** {resp.blocked_claims_count}", "", "## Claims"]
    for c in resp.claims:
        lines.append(f"- [{c.status}] {c.text} ({_claim_sources(c)})")
    lines += ["", "## Contradictions"]
    for c in resp.contradictions:
        lines.append(f"- {c.subject} [{c.status}]: {c.explanation}")
    lines += ["", "## Amendment Chains"]
    for c in resp.amendment_chains:
        lines.append(f"- {c.subject}: {' -> '.join(c.doc_ids_ordered)} active={c.active_doc_name}")
    return "\n".join(lines)


def _claim_sources(c) -> str:
    if not c.citations:
        return "no citations"
    return "; ".join(f"{cit.doc_name} p.{cit.page}" for cit in c.citations)


@app.get("/api/contradictions")
async def get_contradictions(doc_ids: str | None = None) -> dict[str, Any]:
    """Corpus-wide, amendment-aware scan. Conflicts explained by the amendment graph (including
    transitive ones such as v1 vs v3) and superseded documents are excluded; headings and bare
    section numbers are never compared."""
    from app.contradictions.detector import scan_corpus_contradictions
    from app.qa.service import _resolve_nli

    ids = [d.strip() for d in doc_ids.split(",") if d.strip()] if doc_ids else None
    try:
        nli = _resolve_nli(None) if settings.enable_nli else None
    except Exception as e:  # NLI is informational here; the typed-value check is deterministic
        logger.warning("NLI unavailable for /api/contradictions: %s", e)
        nli = None
    found = scan_corpus_contradictions(store, nli_provider=nli, doc_ids=ids)
    return {"contradictions": [c.model_dump() for c in found], "count": len(found)}
