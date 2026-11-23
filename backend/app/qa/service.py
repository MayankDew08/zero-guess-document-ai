from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime
from typing import Any

from app.amendments.graph import active_chain_doc_ids, build_amendment_chains, superseded_doc_ids
from app.calculator.service import calculate, is_calculation_query
from app.contradictions.detector import detect_contradictions
from app.core.config import settings
from app.core.logging import get_logger
from app.core.store import AppStore, store
from app.models.schemas import (
    AskResponse,
    ChatTurn,
    DraftAnswer,
    DraftClaim,
    Gate1Trace,
    Gate2Trace,
    Gate3Trace,
    Gate4Trace,
    PipelineTrace,
)
from app.qa.decompose import split_question_parts
from app.qa.followup import MAX_HISTORY_TURNS, build_clarification, plan_turn
from app.qa.llm import LLMProvider, OllamaLLMProvider
from app.qa.prompt import build_claim_prompt, is_hindi
from app.qa.translate import render_claims_in_hindi
from app.retrieval.embeddings import EmbeddingProvider
from app.retrieval.reranker import RerankerProvider
from app.retrieval.service import retrieve
from app.scoring.faithfulness import compute_faithfulness
from app.verification.nli import HFNLIProvider, NLIProvider
from app.verification.pipeline import resolve_and_verify_claims

logger = get_logger(__name__)

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


def _build_trace(retrieval, draft, shown, blocked, edges, contradictions, chains_found, abstained) -> PipelineTrace:
    claims = shown + blocked
    reached = [c for c in claims if c.numeric_verification is not None]  # got through Gate 2 into Gate 3
    invalid = [c for c in blocked if (c.reason or "").startswith(("unresolved_source_id", "no_source_ids"))]
    nli_ok = sum(1 for c in reached if c.citations and c.citations[0].nli_label in {"entailment", "skipped"})
    return PipelineTrace(
        gate1_retrieval=Gate1Trace(
            hybrid_candidates=retrieval.hybrid_candidates, reranked_kept=retrieval.reranked_kept,
            max_rerank_score=retrieval.max_rerank_score, threshold=settings.rerank_abstain_threshold,
            passed=bool(retrieval.crag_passed and retrieval.chunks)),
        gate2_citation_resolution=Gate2Trace(
            drafted_claims=len(draft.claims), resolved_citations=sum(1 for c in claims if c.citations),
            rejected_invalid_ids=len(invalid)),
        gate3_nli_and_numeric=Gate3Trace(
            nli_passed=nli_ok, nli_failed=len(reached) - nli_ok,
            numeric_passed=sum(1 for c in reached if c.numeric_verification.get("ok")),
            numeric_failed=sum(1 for c in reached if not c.numeric_verification.get("ok"))),
        gate4_lineage_and_conflicts=Gate4Trace(
            amendment_chains_found=chains_found, superseded_docs_filtered=len(superseded_doc_ids(edges)),
            unresolved_contradictions=len(contradictions), abstained=abstained),
    )


def _abstain(request_id, question, hindi, missing, debug_info, debug, trace=None) -> AskResponse:
    return AskResponse(
        pipeline_trace=trace, created_at=datetime.now(UTC).isoformat(timespec="seconds"),
        language="hi" if hindi else "en",
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
    history: list[ChatTurn] | None = None,
) -> AskResponse:
    """Conversational entry point. With no history this is exactly `_ask_pipeline`.

    The follow-up layer only decides WHICH QUESTION STRING enters the pipeline (or asks the user for missing
    calculation inputs). Chat history is never passed to retrieval, drafting or verification, so it can never
    be cited: every turn independently passes Gates 1-4 against the stored PDF chunks of `app_store`."""
    plan = plan_turn(question, history, llm=_resolve_llm(llm_provider) if history else None)
    resp = _ask_pipeline(plan.pipeline_question, doc_ids, top_k, debug, app_store, embedding_provider,
                         reranker_provider, nli_provider, llm_provider)
    resp.question = question  # what the user typed; the resolved text is exposed via rewritten_question
    resp.workspace = app_store.workspace
    resp.rewritten_question = plan.rewritten_question
    resp.clarification_needed = build_clarification(plan, app_store)
    if debug and resp.debug is not None:
        resp.debug["followup"] = {"pipeline_question": plan.pipeline_question, "notes": plan.notes,
                                  "history_turns_considered": len((history or [])[-MAX_HISTORY_TURNS:])}
    return resp


def _ask_pipeline(
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
    hindi = is_hindi(question)
    nli = _resolve_nli(nli_provider)
    llm = _resolve_llm(llm_provider)

    # Gate 1: retrieve + rerank + CRAG pre-generation abstention
    # Compound questions ("... and what is ...") are split; every part gets its own retrieval, CRAG gate and draft.
    parts = split_question_parts(question)
    part_results = [retrieve(query=p, top_k=top_k, doc_ids=doc_ids, app_store=app_store,
                             embedding_provider=embedding_provider, reranker_provider=reranker_provider,
                             apply_reranker=True, apply_crag_gate=True) for p in parts]
    retrieval = _merge_retrievals(part_results)
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
            trace = _build_trace(retrieval, DraftAnswer(), [], [], app_store.amendment_edges, [], len(chains), True)
            return _abstain(request_id, question, hindi, [reason] + calc_missing, debug_info, debug, trace)

    shown: list = []
    blocked: list = []
    draft = DraftAnswer()
    if retrieval.chunks and retrieval.crag_passed:
        claims_all: list[DraftClaim] = []
        missing_all: list[str] = []
        raws: list[dict] = []
        for part, rv in zip(parts, part_results, strict=True):
            if not rv.chunks or not rv.crag_passed:  # this part has no proof at all: no LLM call, no guess
                missing_all.append(f"No proof found in the documents for: {part}")
                continue
            prompt = build_claim_prompt(part, rv.chunks, _doc_status(app_store), hindi=False)
            try:
                raw_part = llm.generate_json(prompt)
            except Exception as e:  # LLM down/timeout -> abstain-with-reason, never a guess
                logger.warning("LLM generation failed: %s", e)
                raw_part = {"claims": [], "missing_evidence": [f"LLM unavailable: {e}"]}
            raws.append(raw_part)
            d_part = _route_no_evidence_statements(_parse_draft(raw_part))
            snapped = snap_citations(d_part.claims, [c.chunk for c in rv.chunks], superseded_doc_ids(app_store.amendment_edges))
            if snapped:
                debug_info.setdefault("snapped_citations", []).extend(snapped)
            claims_all.extend(d_part.claims)
            missing_all.extend(d_part.missing_evidence)
        if len(parts) > 1:
            for i, c in enumerate(claims_all, 1):
                c.claim_id = f"c{i}"
            debug_info["question_parts"] = parts
        draft = DraftAnswer(claims=claims_all, missing_evidence=missing_all)
        raw_draft = raws[0] if len(raws) == 1 else raws
        debug_info["llm_raw"] = raw_draft
        debug_info["draft_claims"] = [c.model_dump() for c in draft.claims]
        # Gate 2 + Gate 3
        shown, blocked = resolve_and_verify_claims(draft.claims, app_store, nli)
        if not shown and any(b.citations for b in blocked):  # rejected at Gate 3 (resolved citation, not entailed)
            # Bounded self-repair: every drafted claim failed Gate 2/3. Ask ONCE more (same evidence, same gates) with
            # the blocked claims listed and their sentence ids excluded. Nothing is relaxed: repaired claims are
            # re-verified exactly like the first ones, and the first round's blocked claims stay reported.
            repair = _repair_claims(parts, part_results, blocked, app_store, llm, hindi)
            if repair:
                debug_info["repair_round"] = [c.model_dump() for c in repair]
                shown2, blocked2 = resolve_and_verify_claims(repair, app_store, nli)
                shown, blocked = shown2, blocked + blocked2
                draft = DraftAnswer(claims=list(draft.claims) + repair, missing_evidence=draft.missing_evidence)
        shown = _dedupe_claims(shown)
        if hindi:  # stage 2: verified Hindi rendering of the verified English claims
            hindi_notes = render_claims_in_hindi(shown, llm, nli)
            debug_info["hindi_rendering_notes"] = hindi_notes
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
        trace = _build_trace(retrieval, draft, shown, blocked, app_store.amendment_edges, contradictions, len(chains), True)
        resp = _abstain(request_id, question, hindi, missing_evidence, debug_info, debug, trace)
        resp.blocked_claims = blocked
        resp.amendment_chains = chains  # lineage of the retrieved documents is context, not an unverified claim
        resp.blocked_claims_count = len(blocked)
        resp.drafted_claims_count = fa["drafted_claims_count"]
        resp.draft_support_pct = fa["draft_support_pct"]
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
    trace = _build_trace(retrieval, draft, shown, blocked, app_store.amendment_edges, contradictions, len(chains), False)
    resp = AskResponse(
        pipeline_trace=trace, created_at=datetime.now(UTC).isoformat(timespec="seconds"),
        language="hi" if hindi else "en",
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


_REPAIR_RULES = (
    "\n\nREPAIR ROUND: your previous claims were REJECTED by the verifier because the cited sentence did not fully entail them.\n"
    "Rejected claims:\n{rejected}\n"
    "Sentences behind the rejected claims (avoid them if another plain sentence answers the question): {banned}.\n"
    "Write NEW claims: copy the wording of the sentence shown after WHAT THE CITED SENTENCE REALLY SAYS (it is the only thing a claim may say); each must restate ONE cited sentence nearly word-for-word and keep EVERY condition and qualifier it states "
    "(e.g. 'if the delay is attributable to the RE'; 'were to come into effect'); do not generalise it. Prefer short plain "
    "sentences over long table rows, and for a changed date prefer the ACTIVE document's sentence. "
    "If no sentence supports an answer, return \"claims\": [] and say what is missing. Same JSON schema."
)


def _repair_claims(parts, part_results, blocked, app_store, llm, hindi) -> list:
    """One extra drafting round after total Gate-3 rejection. Returns new, still UNVERIFIED DraftClaims."""
    banned = sorted({sid for b in blocked for sid in b.source_ids})
    rejected_texts = {b.text.strip().lower() for b in blocked}
    rejected = "\n".join(
        f"- REJECTED CLAIM: {b.text}\n  WHAT THE CITED SENTENCE REALLY SAYS: \"{(b.citations[0].quote if b.citations else '')[:300]}\"\n"
        f"  WHY: {(b.reason or '').split(' (')[0]}" for b in blocked[:4])
    out: list[DraftClaim] = []
    for part, rv in zip(parts, part_results, strict=True):
        if not rv.chunks or not rv.crag_passed:
            continue
        prompt = build_claim_prompt(part, rv.chunks, _doc_status(app_store), hindi=False) + _REPAIR_RULES.format(
            rejected=rejected, banned=", ".join(banned) or "(none)")
        try:
            raw = llm.generate_json(prompt)
        except Exception as e:
            logger.warning("Repair round LLM failed: %s", e)
            continue
        d = _route_no_evidence_statements(_parse_draft(raw))
        snap_citations(d.claims, [c.chunk for c in rv.chunks], superseded_doc_ids(app_store.amendment_edges))
        for c in d.claims:
            if c.text.strip().lower() not in rejected_texts:  # an identical rejected claim is never re-submitted
                c.claim_id = f"r{len(out) + 1}"
                out.append(c)
    return out


_NO_EVIDENCE_RE = re.compile(
    r"\b(no\s+(?:specific\b[^.]{0,80}?)?(?:evidence|proof|information|mention|data|details?)|"
    r"(?:is|are|was|were|has\s+been|have\s+been)?\s*not\s+(?:found|provided|available|mentioned|specified|stated|given|listed|disclosed)|"
    r"does(?:\s+not|n't)\s+(?:state|specify|mention|provide|contain|say|list|include)|"
    r"no\s+specific[^.]{0,80}?(?:mention|provid|specif|stat|given|list)|"
    r"cannot\s+be\s+(?:determined|found)|unable\s+to|insufficient|missing|there\s+is\s+no|there\s+are\s+no)\b|नहीं|उपलब्ध नहीं",
    re.IGNORECASE,
)


def _route_no_evidence_statements(draft: DraftAnswer) -> DraftAnswer:
    """A source-less 'no evidence for X' statement is not a claim: it is a missing-evidence note."""
    keep, extra = [], []
    for c in draft.claims:
        if not c.source_ids and _NO_EVIDENCE_RE.search(c.text):
            extra.append(c.text)
        else:
            keep.append(c)
    return DraftAnswer(claims=keep, missing_evidence=list(draft.missing_evidence) + extra)


_TOKEN = re.compile(r"[a-z0-9%₹]+")


def _toks(text: str) -> set[str]:
    return set(_TOKEN.findall((text or "").lower()))


def snap_citations(claims: list[DraftClaim], chunks: list, superseded_docs: set[str] | None = None) -> list[dict]:
    """Deterministic repair of an off-by-one / wrong sentence_id.

    If a claim restates (>=80% of its words) some retrieved sentence but barely overlaps the sentence it cites,
    cite the sentence it actually restates. Only sentences from the retrieved evidence are eligible, and the
    claim still has to pass NLI + numeric checks against the new quote."""
    sents = {s.sentence_id: _toks(s.text) for ch in chunks for s in ch.sentences}
    doc_of = {s.sentence_id: ch.doc_id for ch in chunks for s in ch.sentences}
    old_docs = superseded_docs or set()
    out: list[dict] = []
    for c in claims:
        ct = _toks(c.text)
        if not c.source_ids or not ct:
            continue
        sim = lambda sid: len(ct & sents.get(sid, set())) / len(ct)  # noqa: E731  (containment of claim in sentence)
        cur = max((sim(sid) for sid in c.source_ids), default=0.0)
        cited_active = any(doc_of.get(sid) not in old_docs for sid in c.source_ids)
        # never "repair" a citation from a live document onto a SUPERSEDED document's look-alike sentence
        pool = [sid for sid in sents if not (cited_active and doc_of.get(sid) in old_docs)]
        best_sid = max(pool, key=sim, default=None)
        if best_sid and best_sid not in c.source_ids and sim(best_sid) >= 0.8 and sim(best_sid) > cur + 0.2:
            out.append({"claim_id": c.claim_id, "from": list(c.source_ids), "to": best_sid, "similarity": round(sim(best_sid), 2)})
            c.source_ids = [best_sid]
    return out


def _merge_retrievals(results: list):
    """One RetrievalResult for tracing/contradictions: union of chunks; passes if any part passed."""
    if len(results) == 1:
        return results[0]
    seen: set[str] = set()
    chunks = []
    for r in results:
        for rc in r.chunks:
            if rc.chunk.chunk_id not in seen:
                seen.add(rc.chunk.chunk_id)
                chunks.append(rc)
    scores = [r.max_rerank_score for r in results if r.max_rerank_score is not None]
    first = results[0]
    return first.model_copy(update={
        "chunks": chunks, "crag_passed": any(r.crag_passed and r.chunks for r in results),
        "max_rerank_score": max(scores) if scores else None,
        "hybrid_candidates": sum(r.hybrid_candidates for r in results),
        "reranked_kept": sum(r.reranked_kept for r in results)})


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


_CLAIM_TYPES = ("factual", "numeric", "date", "rule", "definition", "other")


def _norm_claim_type(raw) -> str:
    """LLMs sometimes echo the schema placeholder ('numeric|rule'): take the first valid type, else 'factual'."""
    for tok in re.split(r"[|,/\s]+", str(raw or "").lower()):
        if tok in _CLAIM_TYPES:
            return tok
    return "factual"


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
                claim_type=_norm_claim_type(c.get("claim_type")),
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
