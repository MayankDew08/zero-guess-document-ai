from __future__ import annotations

import uuid
from typing import Any

from app.amendments.graph import build_amendment_chains
from app.contradictions.detector import detect_contradictions
from app.core.config import settings
from app.core.logging import get_logger
from app.core.store import AppStore, store
from app.models.schemas import AskResponse, DraftAnswer, DraftClaim, RetrievalResult
from app.qa.llm import LLMProvider, OllamaLLMProvider
from app.qa.prompt import build_claim_prompt
from app.retrieval.embeddings import EmbeddingProvider
from app.retrieval.reranker import RerankerProvider
from app.retrieval.service import retrieve
from app.scoring.faithfulness import compute_faithfulness
from app.verification.nli import NLIProvider, HFNLIProvider
from app.verification.pipeline import resolve_and_verify_claims

logger = get_logger(__name__)


def ask_question(
    question: str,
    doc_ids: list[str] | None = None,
    top_k: int | None = None,
    debug: bool = False,
    app_store: AppStore = store,
    embedding_provider: EmbeddingProvider | None = None,
    reranker_provider: RerankerProvider | None = None,
    nli_provider: NLIProvider | None = None,
    llm_provider: LLMProvider | None = None,
) -> AskResponse:
    request_id = f"req_{uuid.uuid4().hex[:12]}"
    top_k = top_k or settings.hybrid_top_k
    if nli_provider is None:
        try:
            nli = HFNLIProvider.get_instance()
        except Exception as e:
            logger.warning("NLI unavailable, falling back to FakeNLIProvider: %s", e)
            from app.verification.nli import FakeNLIProvider
            nli = FakeNLIProvider()
    else:
        nli = nli_provider
    llm = llm_provider or OllamaLLMProvider()

    # Retrieve + rerank + Gate 1 CRAG
    retrieval = retrieve(
        query=question,
        top_k=top_k,
        doc_ids=doc_ids,
        app_store=app_store,
        embedding_provider=embedding_provider,
        reranker_provider=reranker_provider,
        apply_reranker=True,
        apply_crag_gate=True,
    )

    debug_info: dict[str, Any] = {
        "retrieval": {
            "total_indexed_chunks": retrieval.total_indexed_chunks,
            "crag_passed": retrieval.crag_passed,
            "max_rerank_score": retrieval.max_rerank_score,
            "chunks": [
                {
                    "chunk_id": r.chunk.chunk_id,
                    "doc_name": r.chunk.doc_name,
                    "page": r.chunk.page,
                    "score": r.score,
                    "rerank_score": r.rerank_score,
                }
                for r in retrieval.chunks
            ],
        }
    }

    if not retrieval.chunks or not retrieval.crag_passed:
        reason = "No relevant evidence found." if not retrieval.chunks else "Evidence relevance below CRAG threshold."
        return AskResponse(
            request_id=request_id,
            question=question,
            status="abstained",
            answer="I don't have proof in the provided documents to answer this question.",
            claims=[],
            blocked_claims=[],
            contradictions=[],
            amendment_chains=[],
            faithfulness_pct=None,
            verified_sentences_count=0,
            total_shown_sentences=0,
            blocked_claims_count=0,
            missing_evidence=[reason],
            debug=debug_info if debug else None,
        )

    # Draft claims - LLM cites sentence_ids only
    prompt = build_claim_prompt(question, retrieval.chunks)
    try:
        raw_draft = llm.generate_json(prompt)
    except Exception as e:
        logger.warning("LLM generation failed: %s", e)
        raw_draft = {"claims": [], "missing_evidence": [f"LLM unavailable: {e}"]}
    draft = _parse_draft(raw_draft)
    debug_info["llm_raw"] = raw_draft
    debug_info["draft_claims"] = [c.model_dump() for c in draft.claims]

    # Gate 2 + 3: resolve and verify
    shown_claims, blocked_claims = resolve_and_verify_claims(draft.claims, app_store, nli)
    debug_info["verification"] = {
        "shown": [c.model_dump() for c in shown_claims],
        "blocked": [c.model_dump() for c in blocked_claims],
    }

    # Amendment-aware contradiction detection
    contradictions = detect_contradictions(shown_claims, retrieval, app_store.amendment_edges, nli_provider=nli)
    # Amendment chains relevant to retrieved docs
    doc_name_by_id = {d.doc_id: d.doc_name for d in app_store.documents.values()}
    amendment_chains = build_amendment_chains(app_store.amendment_edges, doc_name_by_id)
    # Filter to relevant chains
    retrieved_doc_ids = {r.chunk.doc_id for r in retrieval.chunks}
    amendment_chains = [c for c in amendment_chains if any(d in retrieved_doc_ids for d in c.doc_ids_ordered)] or amendment_chains[:2]

    # Mark claims contradicted if involved in confirmed contradictions? keep status but surface contradictions
    contradicted_ids = set()
    for ctr in contradictions:
        if ctr.status == "confirmed":
            contradicted_ids.update(ctr.affected_claim_ids)
    for c in shown_claims:
        if c.claim_id in contradicted_ids and c.status == "supported":
            c.status = "contradicted"
            c.reason = (c.reason or "") + ";in_confirmed_contradiction"

    # Gate 4: abstain if nothing survives as supported
    supported = [c for c in shown_claims if c.status == "supported"]
    contradicted = [c for c in shown_claims if c.status == "contradicted"]
    display_claims = supported + contradicted  # show supported and contradicted; blocked are counted separately

    faithfulness = compute_faithfulness(display_claims)
    missing_evidence = list(draft.missing_evidence)
    if not display_claims:
        missing_evidence.append("No claims could be verified against cited evidence.")
        status = "abstained"
        answer = "I don't have proof in the provided documents to answer this question."
        faithfulness_pct = None
    else:
        if supported and not contradicted and not missing_evidence:
            status = "answered"
        elif supported and (contradicted or missing_evidence):
            status = "partially_answered" if supported else "contradicted"
        elif contradicted and not supported:
            status = "contradicted"
        else:
            status = "partially_answered"
        answer = _compose_answer(display_claims, contradictions, amendment_chains, missing_evidence)
        faithfulness_pct = faithfulness["faithfulness_pct"]

    resp = AskResponse(
        request_id=request_id,
        question=question,
        status=status,
        answer=answer,
        claims=display_claims,
        blocked_claims=blocked_claims,
        contradictions=contradictions,
        amendment_chains=amendment_chains,
        faithfulness_pct=faithfulness_pct,
        verified_sentences_count=faithfulness["verified_sentences_count"],
        total_shown_sentences=faithfulness["total_shown_sentences"],
        blocked_claims_count=len(blocked_claims),
        missing_evidence=missing_evidence,
        debug=debug_info if debug else None,
    )
    _write_debug_report(resp, debug_info)
    return resp


def _parse_draft(raw: dict[str, Any]) -> DraftAnswer:
    claims_raw = raw.get("claims", []) if isinstance(raw, dict) else []
    claims: list[DraftClaim] = []
    for i, c in enumerate(claims_raw):
        if not isinstance(c, dict):
            continue
        text = str(c.get("text") or c.get("claim") or "").strip()
        source_ids = c.get("source_ids") or c.get("sources") or []
        if isinstance(source_ids, str):
            source_ids = [source_ids]
        source_ids = [str(s).strip() for s in source_ids if str(s).strip()]
        if not text:
            continue
        claims.append(
            DraftClaim(
                claim_id=str(c.get("claim_id") or f"c{i+1}"),
                text=text,
                claim_type=str(c.get("claim_type") or "factual"),
                source_ids=source_ids,
            )
        )
    missing = raw.get("missing_evidence", []) if isinstance(raw, dict) else []
    if isinstance(missing, str):
        missing = [missing]
    missing = [str(m).strip() for m in missing if str(m).strip()]
    return DraftAnswer(claims=claims, missing_evidence=missing)


def _compose_answer(claims, contradictions, amendment_chains, missing_evidence) -> str:
    parts: list[str] = []
    supported = [c for c in claims if c.status == "supported"]
    contradicted = [c for c in claims if c.status == "contradicted"]
    for c in supported:
        parts.append(c.text)
    if contradicted:
        parts.append("Some claims conflict with cited evidence and are flagged as contradictions.")
    if amendment_chains:
        resolved = [ch for ch in amendment_chains if ch.status == "resolved" and ch.active_doc_name]
        if resolved:
            ch = resolved[0]
            parts.append(f"Amendment chain indicates active rule is from {ch.active_doc_name}.")
    if missing_evidence:
        parts.append("Missing evidence: " + "; ".join(missing_evidence[:2]))
    return " ".join(parts).strip() or "I don't have proof in the provided documents to answer this question."


def _write_debug_report(resp: AskResponse, debug_info: dict[str, Any]) -> None:
    try:
        settings.report_path.mkdir(parents=True, exist_ok=True)
        path = settings.report_path / f"debug_{resp.request_id}.json"
        import json

        payload = resp.model_dump()
        payload["debug"] = debug_info
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:
        logger.warning("Failed to write debug report: %s", e)
