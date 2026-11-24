from __future__ import annotations

import asyncio
import json
import queue
import threading
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response, StreamingResponse

from app.core.config import settings
from app.core.logging import get_logger, setup_logging
from app.core.store import (
    DEFAULT_WORKSPACE,
    WORKSPACES,
    AppStore,
    get_store,
    is_valid_workspace,
    store,
)
from app.ingestion.service import (
    clear_all_documents,
    ingest_pdf_file,
    ingest_samples,
    rebuild_runtime_index,
    remove_document,
)
from app.models.schemas import AskRequest, AskResponse, ReportRequest, ReportResponse
from app.qa.llm import OllamaLLMProvider
from app.qa.service import ask_question
from app.retrieval.reranker import CrossEncoderRerankerProvider
from app.verification.nli import HFNLIProvider

setup_logging()
logger = get_logger(__name__)


def _ws(workspace: str) -> AppStore:
    """Resolve a workspace name to its isolated store (400 on unknown). The bank_official store is read from
    this module's `store` global at call time. All workspaces share the same singleton ML models."""
    if not is_valid_workspace(workspace):
        raise HTTPException(status_code=400, detail=f"Unknown workspace '{workspace}'. Valid: {', '.join(WORKSPACES)}")
    return store if workspace == DEFAULT_WORKSPACE else get_store(workspace)


@asynccontextmanager
async def lifespan(_: FastAPI):
    settings.data_path.mkdir(parents=True, exist_ok=True)
    settings.index_path.mkdir(parents=True, exist_ok=True)
    settings.sample_path.mkdir(parents=True, exist_ok=True)
    settings.report_path.mkdir(parents=True, exist_ok=True)
    # Load each workspace's persisted index (bank_official also accepts the legacy flat data/index/ layout)
    to_warm: list[AppStore] = []
    for ws in WORKSPACES:
        st = _ws(ws)
        loaded = st.load(settings.index_path_for(ws)) or (ws == DEFAULT_WORKSPACE and st.load(settings.index_path))
        if loaded:
            logger.info("[%s] Loaded persisted index: %s docs, %s chunks", ws, len(st.documents), len(st.chunks))
            to_warm.append(st)

    async def _warm() -> None:
        """Warm every local model ONCE, in order, in the background (the API binds immediately).

        Ordering matters: the HF models are memory/disk heavy and Ollama preloading is too, so running them
        concurrently makes a cold boot thrash the disk and turns the first question into minutes of dead air.
        """
        for st in to_warm:
            try:
                await asyncio.to_thread(rebuild_runtime_index, None, st)
            except Exception as e:
                logger.warning("[%s] Failed to rebuild runtime index on startup: %s", st.workspace, e)
        # The index rebuild above loads the embedding model; preload the other two singletons the first question
        # needs, otherwise their one-time load (~14s + ~6s) shows up as unexplained latency on the first answer.
        preloads: list[Any] = []
        if settings.enable_reranker and (settings.reranker_provider or "none").lower() not in {"none", "off", "disabled", "false"}:
            preloads.append(CrossEncoderRerankerProvider.get_instance())
        if settings.enable_nli and (settings.nli_provider or "hf").lower() in {"hf", "huggingface"}:
            preloads.append(HFNLIProvider.get_instance())
        for provider in preloads:
            try:
                await asyncio.to_thread(provider.preload)
            except Exception as e:
                logger.warning("Failed to preload %s: %s", type(provider).__name__, e)
        # Last: pull the generator into RAM/VRAM so the first question doesn't pay the cold load either.
        if (settings.llm_provider or "ollama").strip().lower() not in {"mock", "fake", "heuristic", "extractive"}:
            if await asyncio.to_thread(OllamaLLMProvider().warm):
                logger.info("Preloaded Ollama model %s", settings.ollama_model)
        logger.info("Warm-up complete: all local models loaded")

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
        "workspaces": {ws: {"docs": len(_ws(ws).documents), "chunks": len(_ws(ws).chunks)} for ws in WORKSPACES},
    }


def _corpus_summary(st: AppStore | None = None) -> dict[str, Any]:
    from app.amendments.graph import superseded_doc_ids

    st = st if st is not None else store
    return {
        "workspace": st.workspace,
        "documents": len(st.documents),
        "pages": sum(d.num_pages for d in st.documents.values()),
        "chunks": len(st.chunks),
        "table_chunks": sum(1 for c in st.chunks.values() if c.chunk_type == "table"),
        "sentences": len(st.sentence_index),
        "amendment_edges": len(st.amendment_edges),
        "superseded_docs": len(superseded_doc_ids(st.amendment_edges)),
        "indexed": st.embeddings is not None,
    }


def _persist_after_change(st: AppStore | None = None) -> None:
    st = st if st is not None else store
    try:
        rebuild_runtime_index(app_store=st)
        st.save(settings.index_path_for(st.workspace))
    except Exception as e:
        logger.warning("[%s] Index rebuild/save failed: %s", st.workspace, e)


@app.get("/api/workspaces/summary")
async def workspaces_summary() -> dict[str, Any]:
    """Per-workspace compliance health: documents, chunks, amendment chains and unresolved contradictions.
    Deterministic (typed-value comparison + amendment graph); no model is loaded for it."""
    from app.amendments.graph import build_amendment_chains
    from app.contradictions.detector import scan_corpus_contradictions

    out: dict[str, Any] = {}
    for ws in WORKSPACES:
        st = _ws(ws)
        names = {d.doc_id: d.doc_name for d in st.documents.values()}
        found = scan_corpus_contradictions(st, nli_provider=None)
        out[ws] = {
            "doc_count": len(st.documents),
            "chunk_count": len(st.chunks),
            "amendment_chains_count": len(build_amendment_chains(st.amendment_edges, names)),
            "unresolved_contradictions_count": len(found),
            "contradiction_subjects": sorted({c.subject for c in found}),
            "doc_names": [d.doc_name for d in st.documents.values()],
        }
    return {"workspaces": out}


@app.delete("/api/documents/{doc_id}")
async def delete_document(doc_id: str, workspace: str = DEFAULT_WORKSPACE) -> dict[str, Any]:
    """Remove one document: its chunks, sentences and amendment edges; rebuild and persist the index."""
    st = _ws(workspace)
    doc = st.documents.get(doc_id)
    if doc is None:
        raise HTTPException(status_code=404, detail=f"Document {doc_id} not found")
    remove_document(doc_id, st)
    _persist_after_change(st)
    return {"deleted": doc_id, "doc_name": doc.doc_name, "summary": _corpus_summary(st)}


@app.delete("/api/documents")
async def clear_corpus(workspace: str = DEFAULT_WORKSPACE) -> dict[str, Any]:
    """Clear one workspace (documents, chunks, edges, vectors) and persist the empty index."""
    st = _ws(workspace)
    n = len(st.documents)
    clear_all_documents(st)
    _persist_after_change(st)
    return {"deleted_documents": n, "summary": _corpus_summary(st)}


@app.get("/api/documents")
async def list_documents(workspace: str = DEFAULT_WORKSPACE) -> dict[str, Any]:
    st = _ws(workspace)
    return {"workspace": workspace, "documents": [d.model_dump() for d in st.documents.values()], "summary": _corpus_summary(st)}


@app.api_route("/api/documents/{doc_id}/page/{page}/render", methods=["GET", "POST"])
async def render_document_page(doc_id: str, page: int, sentence_id: str | None = None, bbox: str | None = None,
                               workspace: str = DEFAULT_WORKSPACE):
    """Render a PDF page as PNG. With `sentence_id` (or `bbox=x0,y0,x1,y1` in PDF points) the exact
    passage is highlighted in translucent yellow with an amber border."""
    st = _ws(workspace)
    doc = st.documents.get(doc_id)
    if doc is None:
        raise HTTPException(status_code=404, detail=f"Document {doc_id} not found")
    if page < 1 or page > doc.num_pages:
        raise HTTPException(status_code=400, detail=f"Page {page} out of range (1-{doc.num_pages})")
    rects: list[tuple[float, float, float, float]] = []
    pipe_cells: list[str] | None = None
    if sentence_id:
        sent = st.get_sentence(sentence_id)
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
async def ingest(files: list[UploadFile] = File(...), workspace: str = DEFAULT_WORKSPACE) -> dict[str, Any]:
    st = _ws(workspace)
    documents = []
    errors = []
    for f in files:
        safe_name = Path(f.filename or "upload.pdf").name or "upload.pdf"  # never trust client path components
        tmp_path = settings.uploads_path_for(workspace) / safe_name
        tmp_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            content = await f.read()
            tmp_path.write_bytes(content)
            doc = ingest_pdf_file(tmp_path, original_name=safe_name, app_store=st)
            documents.append(doc.model_dump())
        except Exception as e:
            logger.exception("Ingest failed for %s", f.filename)
            errors.append({"doc_name": f.filename, "error": str(e)})
    try:
        rebuild_runtime_index(app_store=st)
        st.save(settings.index_path_for(workspace))
    except Exception as e:
        logger.warning("Index rebuild/save after ingest failed: %s", e)
    return {"workspace": workspace, "documents": documents, "errors": errors}


@app.post("/api/ingest/samples")
async def ingest_samples_endpoint(workspace: str = DEFAULT_WORKSPACE) -> dict[str, Any]:
    """Reset the workspace and ingest the bundled 4-PDF demo corpus."""
    st = _ws(workspace)
    documents, errors = ingest_samples(reset=True, app_store=st)
    warnings = [w for w in errors if w]
    try:
        rebuild_runtime_index(app_store=st)
        st.save(settings.index_path_for(workspace))
    except Exception as e:
        logger.exception("Index rebuild/save after sample ingest failed")
        warnings.append({"error": f"index rebuild failed: {e}"})
    return {
        "workspace": workspace,
        "documents": [d.model_dump() for d in documents],
        "errors": warnings,
        "total_chunks": len(st.chunks),
        "table_chunks": sum(1 for c in st.chunks.values() if c.chunk_type == "table"),
        "amendment_edges": [e.model_dump() for e in st.amendment_edges],
    }


def _ask_payload(resp: AskResponse) -> dict[str, Any]:
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


# Plain `def` (not async): the pipeline is synchronous and CPU/LLM bound, so FastAPI runs it in its threadpool
# instead of blocking the event loop (and /api/health) for the whole request.
@app.post("/api/ask")
def ask(req: AskRequest) -> dict[str, Any]:
    if not req.question.strip():
        raise HTTPException(status_code=400, detail="question is required")
    try:
        resp = ask_question(
            question=req.question.strip(),
            doc_ids=req.doc_ids,
            top_k=req.top_k,
            debug=req.debug,
            app_store=_ws(req.workspace),
            history=req.history,
        )
        return _ask_payload(resp)
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Ask failed")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/ask/stream")
def ask_stream(req: AskRequest) -> StreamingResponse:
    """Same pipeline as /api/ask, streamed as SSE: `stage` events (real progress), then one `result` (the full
    AskResponse payload) or `error`. Validation errors are raised before streaming starts (normal HTTP status)."""
    question = req.question.strip()
    if not question:
        raise HTTPException(status_code=400, detail="question is required")
    app_store = _ws(req.workspace)
    events: queue.Queue[tuple[str, Any] | None] = queue.Queue()

    def worker() -> None:
        try:
            resp = ask_question(
                question=question, doc_ids=req.doc_ids, top_k=req.top_k, debug=req.debug, app_store=app_store,
                history=req.history, on_stage=lambda e: events.put(("stage", e.model_dump())),
            )
            events.put(("result", _ask_payload(resp)))
        except Exception as e:
            logger.exception("Ask (stream) failed")
            events.put(("error", {"detail": str(e)}))
        finally:
            events.put(None)

    threading.Thread(target=worker, daemon=True, name="ask-stream").start()

    def gen():
        while True:
            try:
                item = events.get(timeout=15)
            except queue.Empty:
                yield ": keepalive\n\n"  # keeps proxies/browsers from closing an idle stream during slow model loads
                continue
            if item is None:
                return
            kind, payload = item
            yield f"event: {kind}\ndata: {json.dumps(payload, default=str)}\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


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
            app_store=_ws(req.workspace),
            history=req.history,
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
    except HTTPException:
        raise
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
    result = retrieve(query=question, top_k=top_k, doc_ids=doc_ids, app_store=_ws(str(payload.get("workspace") or DEFAULT_WORKSPACE)))
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
async def get_contradictions(doc_ids: str | None = None, workspace: str = DEFAULT_WORKSPACE) -> dict[str, Any]:
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
    found = scan_corpus_contradictions(_ws(workspace), nli_provider=nli, doc_ids=ids)
    return {"workspace": workspace, "contradictions": [c.model_dump() for c in found], "count": len(found)}
