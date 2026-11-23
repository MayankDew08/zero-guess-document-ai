from __future__ import annotations

import re
import uuid
from typing import Any

from app.amendments.graph import active_chain_doc_ids, build_amendment_chains, superseded_doc_ids
from app.calculator.service import calculate, is_calculation_query
from app.contradictions.detector import detect_contradictions
from app.core.config import settings
from app.core.logging import get_logger
from app.core.store import AppStore, store
from app.models.schemas import AskResponse, DraftAnswer, DraftClaim
from app.qa.llm import LLMProvider, OllamaLLMProvider
from app.qa.prompt import build_claim_prompt
from app.retrieval.embeddings import EmbeddingProvider
from app.retrieval.reranker import RerankerProvider
from app.retrieval.service import retrieve
from app.scoring.faithfulness import compute_faithfulness
from app.verification.nli import HFNLIProvider, NLIProvider
from app.verification.pipeline import resolve_and_verify_claims

logger = get_logger(__name__)

_DEVANAGARI = re.compile(r"[\u0900-\u097F]")
ABSTAIN_EN = "I don't have proof in the provided documents to answer this question."
ABSTAIN_HI = "मेरे पास दिए गए दस्तावेज़ों में इसका प्रमाण नहीं है। (I don't have proof in the provided documents to answer this question.)"


def _resolve_nli(nli_provider: NLIProvider | None) -> NLIProvider | None:
    if nli_provider is not None:
        return nli_provider
    name = (settings.nli_provider or "hf").lower()
    if name in {"mock", "fake", "heuristic"}:
        from app.verification.nli import FakeNLIProvider
        return FakeNLIProvider()
    if name in {"none", "disabled", "off"}:
        return None
    return HFNLIProvider.get_instance()


def _resolve_llm(llm_provider: LLMProvider | None) -> LLMProvider:
    if llm_provider is not None:
        return llm_provider
    if (settings.llm_provider or "ollama").lower() in {"mock", "fake", "heuristic", "extractive"}:
        from app.qa.llm import FakeLLMProvider
        return FakeLLMProvider()
    return OllamaLLMProvider()


def _doc_status(app_store: AppStore) -> dict[str, str]:
    edges = app_store.amendment_edges
    names = {d.doc_id: d.doc_name for d in app_store.documents.values()}
    status: dict[str, str] = {}
    newer_of = {e.to_doc_id: e.from_doc_id for e in edges}
    for doc_id in names:
        if doc_id in superseded_doc_ids(edges):
            status[doc_id] = f"SUPERSEDED (replaced by {names.get(newer_of.get(doc_id), newer_of.get(doc_id))}); historical only"
        elif doc_id in active_chain_doc_ids(edges):
            status[doc_id] = "ACTIVE (latest in its amendment chain)"
        else:
            status[doc_id] = "STANDALONE (no amendment link)"
    return status


def _abstain(request_id, question, hindi, missing, debug_info, debug) -> AskResponse:
    return AskResponse(
        request_id=request_id, question=question, status="abstained",
        answer=ABSTAIN_HI if hindi else ABSTAIN_EN,
        faithfulness_pct=None, missing_evidence=missing, confidence=0.0,
        confidence_breakdown={"retrieval": 0.0, "verification": 0.0, "contradiction_penalty": 0.0},
        debug=debug_info if debug else None,
    )


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
    hindi = bool(_DEVANAGARI.search(question))
    nli = _resolve_nli(nli_provider)
    llm = _resolve_llm(llm_provider)

    # Gate 1: retrieve + rerank + CRAG pre-generation abstention
    retrieval = retrieve(query=question, top_k=top_k, doc_ids=doc_ids, app_store=app_store,
                         embedding_provider=embedding_provider, reranker_provider=reranker_provider,
                         apply_reranker=True, apply_crag_gate=True)
    debug_info: dict[str, Any] = {"retrieval": {
        "total_indexed_chunks": retrieval.total_indexed_chunks, "crag_passed": retrieval.crag_passed,
        "max_rerank_score": retrieval.max_rerank_score,
        "chunks": [{"chunk_id": r.chunk.chunk_id, "doc_name": r.chunk.doc_name, "page": r.chunk.page,
                    "score": r.score, "rerank_score": r.rerank_score} for r in retrieval.chunks]}}

    doc_name_by_id = {d.doc_id: d.doc_name for d in app_store.documents.values()}
    chains = build_amendment_chains(app_store.amendment_edges, doc_name_by_id)

    # Deterministic calculator needs no LLM: rate comes from a verified sentence of the active rule.
    calculation, calc_missing = (None, [])
    if is_calculation_query(question):
        pre_ctr = detect_contradictions([], retrieval, app_store.amendment_edges, nli_provider=None,
                                        app_store=app_store, question="late payment fee interest rate " + question)
        calculation, calc_missing = calculate(question, app_store, pre_ctr)

    if not retrieval.chunks or not retrieval.crag_passed:
        reason = "No relevant evidence found." if not retrieval.chunks else (
            f"Evidence relevance ({retrieval.max_rerank_score or 0:.2f}) is below the CRAG threshold ({settings.rerank_abstain_threshold}).")
        if calculation is None:
            return _abstain(request_id, question, hindi, [reason] + calc_missing, debug_info, debug)

    shown: list = []
    blocked: list = []
    draft = DraftAnswer()
    if retrieval.chunks and retrieval.crag_passed:
        prompt = build_claim_prompt(question, retrieval.chunks, _doc_status(app_store))
        try:
            raw_draft = llm.generate_json(prompt)
        except Exception as e:  # LLM down/timeout -> abstain-with-reason, never a guess
            logger.warning("LLM generation failed: %s", e)
            raw_draft = {"claims": [], "missing_evidence": [f"LLM unavailable: {e}"]}
        draft = _parse_draft(raw_draft)
        debug_info["llm_raw"] = raw_draft
        debug_info["draft_claims"] = [c.model_dump() for c in draft.claims]
        # Gate 2 + Gate 3
        shown, blocked = resolve_and_verify_claims(draft.claims, app_store, nli)
        shown = _dedupe_claims(shown)
        debug_info["verification"] = {"shown": [c.model_dump() for c in shown], "blocked": [c.model_dump() for c in blocked]}

    # Amendment-aware contradiction detection (conflicts explained by the amendment graph are excluded)
    contradictions = []
    if settings.enable_contradictions:
        contradictions = detect_contradictions(shown, retrieval, app_store.amendment_edges, nli_provider=nli,
                                               app_store=app_store, question=question)
        if calculation is not None and not calculation.warnings:
            calculation, _ = calculate(question, app_store, contradictions)

    retrieved_doc_ids = {r.chunk.doc_id for r in retrieval.chunks}
    chains = [c for c in chains if set(c.doc_ids_ordered) & retrieved_doc_ids]

    # Gate 4: abstain if nothing survives verification
    # The LLM's own "missing" notes are dropped when the deterministic calculator produced the figure.
    missing_evidence = [] if calculation is not None else list(draft.missing_evidence)
    for b in blocked:
        missing_evidence.append(f"Blocked claim “{b.text}” — {b.reason}")
    fa = compute_faithfulness(shown, blocked)

    if not shown and calculation is None:
        missing_evidence.append("No claims could be verified against cited evidence.")
        resp = _abstain(request_id, question, hindi, missing_evidence, debug_info, debug)
        resp.blocked_claims = blocked
        resp.blocked_claims_count = len(blocked)
        resp.drafted_claims_count = fa["drafted_claims_count"]
        _write_debug_report(resp, debug_info)
        return resp

    conflict_docs = {v.doc_id for ctr in contradictions for v in ctr.values}
    cited_docs = {cit.doc_id for c in shown for cit in c.citations}
    if contradictions and (cited_docs & conflict_docs):
        status = "contradicted"
    elif blocked or draft.missing_evidence:
        status = "partially_answered"
    else:
        status = "answered"
    answer = _compose_answer(shown, calculation, contradictions, chains, hindi)
    confidence, breakdown = _compute_confidence(retrieval, shown, blocked, contradictions, fa["faithfulness_pct"])
    resp = AskResponse(
        request_id=request_id, question=question, status=status, answer=answer,
        claims=shown, blocked_claims=blocked, contradictions=contradictions, amendment_chains=chains,
        faithfulness_pct=fa["faithfulness_pct"], verified_sentences_count=fa["verified_sentences_count"],
        total_shown_sentences=fa["total_shown_sentences"], blocked_claims_count=len(blocked),
        drafted_claims_count=fa["drafted_claims_count"], draft_support_pct=fa["draft_support_pct"],
        missing_evidence=missing_evidence, calculation=calculation,
        confidence=confidence, confidence_breakdown=breakdown, debug=debug_info if debug else None,
    )
    _write_debug_report(resp, debug_info)
    return resp


def _dedupe_claims(claims: list) -> list:
    """1 claim = 1 atomic sentence: drop restatements that cite exactly the same evidence."""
    seen: set[tuple[str, ...]] = set()
    out = []
    for c in claims:
        key = tuple(sorted(c.source_ids))
        if key in seen:
            continue
        seen.add(key)
        out.append(c)
    return out


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


def _compose_answer(shown, calculation, contradictions, chains, hindi) -> str:
    parts: list[str] = []
    if hindi and shown:
        parts.append("सत्यापित उत्तर (verified answer):")
    parts.extend(c.text for c in shown)  # only verified claims form the answer
    if calculation is not None:
        parts.append(f"Calculated (deterministic, from the cited active rule): {calculation.result}.")
    if contradictions:
        parts.append("⚠ Conflicting sources detected — see Contradiction Alerts; not resolved by guessing.")
    resolved = [ch for ch in chains if ch.status == "resolved" and ch.active_doc_name]
    if resolved:
        parts.append(f"Amendment chain: {resolved[0].active_doc_name} is the latest active version.")
    return " ".join(parts).strip() or ABSTAIN_EN


def _compute_confidence(retrieval, display_claims, blocked_claims, contradictions, faithfulness_pct):
    max_rerank = 0.0
    for r in getattr(retrieval, "chunks", []) or []:
        score = r.rerank_score if r.rerank_score is not None else r.score
        if score and score > max_rerank:
            max_rerank = float(score)
    retrieval_score = min(1.0, max_rerank)
    verified = sum(1 for c in display_claims if c.status == "supported")
    total = len(display_claims) + len(blocked_claims)
    verification_score = (verified / total) if total > 0 else 0.0
    contradiction_penalty = min(0.4, 0.15 * len(contradictions or []))
    confidence = max(0.0, min(1.0, 0.45 * retrieval_score + 0.45 * verification_score + 0.10 * (1.0 if total > 0 else 0.0) - contradiction_penalty))
    return round(confidence, 4), {
        "retrieval": round(retrieval_score, 4),
        "verification": round(verification_score, 4),
        "contradiction_penalty": round(contradiction_penalty, 4),
    }

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
