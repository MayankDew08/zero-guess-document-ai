from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from app.core.config import settings
from app.core.logging import get_logger, setup_logging
from app.core.store import store
from app.ingestion.service import ingest_pdf_file, rebuild_runtime_index
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
        try:
            rebuild_runtime_index()
        except Exception as e:
            logger.warning("Failed to rebuild runtime index on startup: %s", e)
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


@app.get("/api/documents")
async def list_documents() -> dict[str, Any]:
    return {"documents": [d.model_dump() for d in store.documents.values()]}


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
async def ingest_samples() -> dict[str, Any]:
    sample_dir = settings.sample_path
    if not sample_dir.exists():
        return {"documents": [], "errors": [{"error": f"Sample directory not found: {sample_dir}"}]}
    pdfs = sorted(sample_dir.glob("*.pdf"))
    if not pdfs:
        return {"documents": [], "errors": [{"error": "No sample PDFs found. Run scripts/generate_samples.py first."}]}
    documents = []
    errors = []
    for p in pdfs:
        try:
            doc = ingest_pdf_file(p)
            documents.append(doc.model_dump())
        except Exception as e:
            logger.exception("Sample ingest failed for %s", p.name)
            errors.append({"doc_name": p.name, "error": str(e)})
    try:
        rebuild_runtime_index()
        store.save(settings.index_path)
    except Exception as e:
        logger.warning("Index rebuild/save after sample ingest failed: %s", e)
    return {"documents": documents, "errors": errors}


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
        return resp.model_dump()
    except Exception as e:
        logger.exception("Ask failed")
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
    claims_html = "".join(
        f"<li><strong>{c.status}</strong>: {c.text}<br><small>{_claim_sources(c)}</small></li>" for c in resp.claims
    )
    blocked_html = "".join(f"<li>{c.text} — {c.reason}</li>" for c in resp.blocked_claims)
    ctr_html = "".join(f"<li><strong>{c.subject}</strong> [{c.status}]: {c.explanation}</li>" for c in resp.contradictions)
    am_html = "".join(
        f"<li><strong>{c.subject}</strong>: {' -> '.join(c.doc_ids_ordered)} (active: {c.active_doc_name})</li>"
        for c in resp.amendment_chains
    )
    return f"""<!doctype html><html><head><meta charset='utf-8'><title>Report {resp.request_id}</title>
    <style>body{{font-family:Arial,sans-serif;margin:2rem;max-width:960px}} .muted{{color:#555}} code{{background:#f3f3f3;padding:2px 4px}}</style></head>
    <body><h1>Zero-Guessing Report</h1>
    <p class='muted'>Request: {resp.request_id}</p>
    <p><strong>Question:</strong> {resp.question}</p>
    <p><strong>Status:</strong> {resp.status}</p>
    <p><strong>Answer:</strong> {resp.answer}</p>
    <p><strong>Faithfulness:</strong> {resp.faithfulness_pct}% ({resp.verified_sentences_count}/{resp.total_shown_sentences})</p>
    <p><strong>Blocked claims:</strong> {resp.blocked_claims_count}</p>
    <h2>Claims</h2><ul>{claims_html or '<li>None</li>'}</ul>
    <h2>Blocked Claims</h2><ul>{blocked_html or '<li>None</li>'}</ul>
    <h2>Contradictions</h2><ul>{ctr_html or '<li>None</li>'}</ul>
    <h2>Amendment Chains</h2><ul>{am_html or '<li>None</li>'}</ul>
    </body></html>"""


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
