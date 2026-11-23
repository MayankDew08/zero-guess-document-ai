#!/usr/bin/env python3
"""Golden Evaluation Benchmark for the Zero-Guessing Document AI.

Two modes, one labelled dataset (data/eval/golden_dataset.json), real local models, no mocks.

  --retrieval-only   Fast, zero LLM calls. 4-way retrieval ablation scored against the gold (doc, page) labels:
                       (a) BM25 only
                       (b) Dense bge-m3 only
                       (c) Hybrid RRF (bge-m3 + BM25)
                       (d) Our pipeline: contextual hybrid + bge-reranker-v2-m3 (question parts, CRAG gate)
                     -> Recall@5, Precision@5, MRR@5 (+ Gate-1 pre-LLM abstention accuracy).

  --full             Single in-process run of the whole pipeline (qwen2.5 via Ollama, bge-m3, bge-reranker-v2-m3,
                     mDeBERTa NLI) -> Faithfulness, Hallucination Leakage, Citation Exact-Match, Abstention Accuracy,
                     Contradiction Precision/Recall, Superseded False-Positive Rate, Amendment Resolution Accuracy,
                     median latency.

Run from the repo root or backend/:
    python backend/scripts/evaluate.py --retrieval-only
    python backend/scripts/evaluate.py --full                    # default corpora: acme,rbi
    python backend/scripts/evaluate.py --full --corpora all      # + hackasol

Results are merged into data/reports/golden_eval_report.json (each mode owns its own section) and a paste-ready
Markdown summary is printed and written to data/reports/golden_eval_report.md.

Isolation: every corpus is ingested into its own throw-away in-memory AppStore and all file side effects
(PDF copies, per-request debug reports) go to a temp dir, so the live workspaces / data/index are never touched.
This script only *imports* production code; it does not modify it.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import platform
import re
import statistics
import subprocess
import sys
import tempfile
import time
import unicodedata
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

BACKEND = Path(__file__).resolve().parents[1]
REPO = BACKEND.parent
sys.path.insert(0, str(BACKEND))

from app.core.config import settings  # noqa: E402

DEFAULT_DATASET = REPO / "data" / "eval" / "golden_dataset.json"
DEFAULT_REPORT = REPO / "data" / "reports" / "golden_eval_report.json"
K = 5
MODES = [
    ("bm25", "(a) BM25 only"),
    ("dense", "(b) Dense bge-m3 only"),
    ("hybrid_rrf", "(c) Hybrid RRF (bge-m3 + BM25)"),
    ("pipeline", "(d) Contextual Hybrid + bge-reranker-v2-m3 (ours)"),
]


# ------------------------------------------------------------------------------------------------ helpers
def log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def pct(num: float, den: float, digits: int = 1) -> float | None:
    return round(100.0 * num / den, digits) if den else None


def fmt_pct(v: float | None) -> str:
    return "n/a" if v is None else f"{v:.1f}%"


def alnum(text: str) -> str:
    """Case/whitespace/punctuation-insensitive form used for independent quote matching."""
    return re.sub(r"[\W_]+", "", unicodedata.normalize("NFKC", text or "").casefold())


def norm_value(text: str) -> str:
    """Normalise for expected_value matching: case, thousands commas and currency markers."""
    t = unicodedata.normalize("NFKC", text or "").casefold()
    t = re.sub(r"₹|\brs\.?|\binr\b", " ", t)
    t = t.replace(",", "")
    return re.sub(r"\s+", " ", t).strip()


def load_dataset(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    data["_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()[:16]
    return data


def git_commit() -> str | None:
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=REPO, capture_output=True,
                              text=True, timeout=5).stdout.strip() or None
    except Exception:
        return None


def isolate_side_effects() -> Path:
    """Redirect PDF copies and per-request debug dumps to a temp dir (never data/documents or data/reports)."""
    tmp = Path(tempfile.mkdtemp(prefix="golden_eval_"))
    settings.data_dir = str(tmp / "data")
    settings.report_dir = str(tmp / "reports")
    settings.index_dir = str(tmp / "index")
    return tmp


class CachedEmbedder:
    """Memoising wrapper around the process-wide bge-m3 singleton: a query embedded once is reused by all 4 modes."""

    def __init__(self, inner):
        self.inner = inner
        self.cache: dict[str, np.ndarray] = {}

    def embed(self, texts: list[str]) -> np.ndarray:
        if not texts:
            return self.inner.embed(texts)
        missing = list(dict.fromkeys(t for t in texts if t not in self.cache))
        if missing:
            for t, v in zip(missing, self.inner.embed(missing), strict=True):
                self.cache[t] = v
        return np.stack([self.cache[t] for t in texts])


def build_corpora(dataset: dict, names: list[str], embedder=None):
    """Ingest each corpus into its own AppStore. Returns (stores, pdf_paths, skipped)."""
    from app.core.store import AppStore
    from app.ingestion.service import ingest_pdf_file
    from app.retrieval.service import build_index

    stores: dict[str, AppStore] = {}
    pdf_paths: dict[str, Path] = {}
    skipped: dict[str, str] = {}
    for name in names:
        spec = dataset["_meta"]["corpora"].get(name)
        if spec is None:
            skipped[name] = "unknown corpus"
            continue
        files = [REPO / f for f in spec["files"]]
        missing = [f.name for f in files if not f.exists()]
        if missing:
            skipped[name] = f"missing PDFs: {', '.join(missing)}"
            log(f"[skip] corpus '{name}': {skipped[name]}")
            continue
        st = AppStore(workspace=f"eval_{name}")
        for f in sorted(files):
            doc = ingest_pdf_file(f, app_store=st)
            pdf_paths[doc.doc_id] = f
        build_index(app_store=st, embedding_provider=embedder)
        stores[name] = st
        log(f"[corpus] {name}: {len(st.documents)} docs, {len(st.chunks)} chunks, {len(st.amendment_edges)} amendment edges")
    return stores, pdf_paths, skipped


def select_cases(dataset: dict, stores: dict, only: list[str] | None) -> list[dict]:
    cases = [c for c in dataset["cases"] if c["corpus"] in stores]
    if only:
        cases = [c for c in cases if c["id"] in set(only)]
    return cases


def environment(dataset: dict, dataset_path: Path) -> dict:
    import torch
    return {
        "python": platform.python_version(), "platform": platform.platform(), "torch": torch.__version__,
        "cuda_available": bool(torch.cuda.is_available()), "git_commit": git_commit(),
        "models": {"llm": f"{settings.llm_provider}:{settings.ollama_model}", "embedding": settings.embedding_model,
                   "embedding_device": settings.embedding_device, "reranker": settings.reranker_model,
                   "reranker_device": settings.reranker_device, "nli": settings.nli_model, "nli_device": settings.nli_device},
        "thresholds": {"rerank_abstain": settings.rerank_abstain_threshold, "hybrid_top_k": settings.hybrid_top_k,
                       "reranker_keep_top_n": settings.reranker_keep_top_n},
        "dataset": {"path": str(dataset_path.relative_to(REPO)) if dataset_path.is_relative_to(REPO) else str(dataset_path),
                    "sha256_16": dataset["_sha256"], "cases_total": len(dataset["cases"])},
    }


# ------------------------------------------------------------------------------------------------ retrieval ablation
def gold_pairs(case: dict) -> set[tuple[str, int]]:
    return {(doc, int(p)) for doc, pages in case["expected_pages"].items() for p in pages}


def rank_bm25(st, query: str, emb) -> list:
    return [st.chunks[cid] for cid, _ in st.bm25.search(query, top_k=K)]


def rank_dense(st, query: str, emb) -> list:
    from app.retrieval.service import _cosine_search

    qvec = emb.embed([query])
    hits = _cosine_search(qvec[0], st.embeddings, K)
    return [st.chunks[st.embedding_chunk_ids[i]] for i, _ in hits]


def rank_hybrid(st, query: str, emb) -> list:
    from app.retrieval.service import retrieve

    res = retrieve(query, top_k=settings.hybrid_top_k, app_store=st, embedding_provider=emb,
                   apply_reranker=False, apply_crag_gate=False)
    return [r.chunk for r in res.chunks]


def rank_pipeline(st, query: str, emb) -> tuple[list, bool, float | None]:
    """Exactly Gate 1 of ask_question: split compound questions, hybrid -> rerank -> CRAG per part.
    Parts are interleaved round-robin so a compound question is not scored on its first part alone."""
    from app.qa.decompose import split_question_parts
    from app.retrieval.service import retrieve

    results = [retrieve(query=p, top_k=settings.hybrid_top_k, app_store=st, embedding_provider=emb,
                        apply_reranker=True, apply_crag_gate=True) for p in split_question_parts(query)]
    merged, seen = [], set()
    for rank in range(max((len(r.chunks) for r in results), default=0)):
        for r in results:
            if rank < len(r.chunks) and r.chunks[rank].chunk.chunk_id not in seen:
                seen.add(r.chunks[rank].chunk.chunk_id)
                merged.append(r.chunks[rank].chunk)
    crag = any(r.crag_passed and r.chunks for r in results)
    scores = [r.max_rerank_score for r in results if r.max_rerank_score is not None]
    return merged, crag, (max(scores) if scores else None)


def score_ranking(ranked: list, gold: set[tuple[str, int]]) -> dict:
    top = ranked[:K]
    hit_pairs = {(c.doc_id, c.page) for c in top} & gold
    relevant = [(c.doc_id, c.page) in gold for c in top]
    first = next((i for i, r in enumerate(relevant, 1) if r), None)
    return {"recall": len(hit_pairs) / len(gold), "precision": (sum(relevant) / len(top)) if top else 0.0,
            "rr": (1.0 / first) if first else 0.0}


def run_retrieval_only(dataset: dict, names: list[str], only: list[str] | None) -> dict:
    from app.retrieval.embeddings import SentenceTransformerEmbeddingProvider

    t_start = time.perf_counter()
    emb = CachedEmbedder(SentenceTransformerEmbeddingProvider.get_instance())
    stores, _, skipped = build_corpora(dataset, names, embedder=emb)
    t_index = time.perf_counter() - t_start
    cases = select_cases(dataset, stores, only)
    if not cases:
        raise SystemExit("No evaluable cases (check --corpora / missing PDFs).")

    per_case, agg = [], {m: [] for m, _ in MODES}
    gate1 = {"abstain_expected": 0, "abstain_expected_caught": 0, "answerable": 0, "answerable_wrongly_abstained": 0}
    t_q = time.perf_counter()
    for case in cases:
        st, q, gold = stores[case["corpus"]], case["question"], gold_pairs(case)
        row: dict = {"id": case["id"], "corpus": case["corpus"], "category": case["category"], "scored": bool(gold)}
        ranked_by_mode = {"bm25": rank_bm25(st, q, emb), "dense": rank_dense(st, q, emb), "hybrid_rrf": rank_hybrid(st, q, emb)}
        pipe, crag, max_rr = rank_pipeline(st, q, emb)
        ranked_by_mode["pipeline"] = pipe
        row["gate1"] = {"crag_passed": crag, "max_rerank_score": None if max_rr is None else round(max_rr, 4)}
        if case["expect_abstention"]:
            gate1["abstain_expected"] += 1
            gate1["abstain_expected_caught"] += int(not crag)
        else:
            gate1["answerable"] += 1
            gate1["answerable_wrongly_abstained"] += int(not crag)
        for mode, ranked in ranked_by_mode.items():
            top = [f"{c.doc_id}:p{c.page}" for c in ranked[:K]]
            if gold:
                s = score_ranking(ranked, gold)
                agg[mode].append({"corpus": case["corpus"], **s})
                row[mode] = {**{k: round(v, 3) for k, v in s.items()}, "top5": top}
            else:
                row[mode] = {"top5": top}
        per_case.append(row)
    t_queries = time.perf_counter() - t_q

    def summarise(rows: list[dict]) -> dict:
        n = len(rows)
        return {"n_cases": n,
                "recall_at_5": round(sum(r["recall"] for r in rows) / n, 4) if n else None,
                "precision_at_5": round(sum(r["precision"] for r in rows) / n, 4) if n else None,
                "mrr_at_5": round(sum(r["rr"] for r in rows) / n, 4) if n else None}

    modes_out = {}
    for mode, label in MODES:
        by_corpus = {c: summarise([r for r in agg[mode] if r["corpus"] == c]) for c in sorted({r["corpus"] for r in agg[mode]})}
        modes_out[mode] = {"label": label, **summarise(agg[mode]), "by_corpus": by_corpus}
    return {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "k": K, "corpora_evaluated": sorted(stores), "corpora_skipped": skipped,
        "cases_total": len(cases), "cases_scored": sum(1 for r in per_case if r["scored"]),
        "relevance_rule": "a retrieved chunk is relevant iff its (doc_id, page) is a gold (doc_id, page) pair",
        "metric_definitions": {
            "recall_at_5": "share of gold (doc, page) pairs covered by the top-5 chunks",
            "precision_at_5": "share of the top-5 chunks that lie on a gold (doc, page)",
            "mrr_at_5": "mean reciprocal rank of the first relevant chunk within the top 5 (0 if none)"},
        "modes": modes_out,
        "gate1_abstention": {
            **gate1,
            "abstention_recall_pct": pct(gate1["abstain_expected_caught"], gate1["abstain_expected"]),
            "false_abstention_pct": pct(gate1["answerable_wrongly_abstained"], gate1["answerable"]),
            "note": "Gate 1 only (CRAG rerank threshold, before any LLM call). Cases that pass Gate 1 can still be refused at Gates 2-4; see --full."},
        "timing_s": {"model_load_and_indexing": round(t_index, 1), "queries_all_modes": round(t_queries, 1),
                     "total": round(time.perf_counter() - t_start, 1)},
        "per_case": per_case,
    }


# ------------------------------------------------------------------------------------------------ full pipeline
class PdfQuoteChecker:
    """Independent citation audit: re-reads the ORIGINAL PDF page with PyMuPDF (not the pipeline's stored chunks)
    and checks that the cited quote really sits on that page (case/space/punctuation-insensitive)."""

    def __init__(self, pdf_paths: dict[str, Path]):
        self.pdf_paths = pdf_paths
        self._pages: dict[tuple[str, int], str] = {}

    def page_norm(self, doc_id: str, page: int) -> str | None:
        key = (doc_id, page)
        if key not in self._pages:
            path = self.pdf_paths.get(doc_id)
            if path is None:
                return None
            import pymupdf

            with pymupdf.open(str(path)) as pdf:
                self._pages[key] = alnum(str(pdf.load_page(page - 1).get_text())) if 1 <= page <= len(pdf) else ""
        return self._pages[key]

    def verbatim(self, doc_id: str, page: int, quote: str) -> bool:
        page_text = self.page_norm(doc_id, page)
        if not page_text or not alnum(quote):
            return False
        if "|" in quote:  # table row rendered as 'cell | cell | cell': every cell must sit on the page
            cells = [alnum(c) for c in quote.split("|") if alnum(c)]
            return bool(cells) and all(c in page_text for c in cells)
        return alnum(quote) in page_text


_NUM_RE = re.compile(r"(?<![A-Za-z])\d[\d,]*(?:\.\d+)?")  # "v3" is a version label, not a figure


def numbers_in(text: str) -> set[str]:
    return {n.replace(",", "").rstrip(".") for n in _NUM_RE.findall(unicodedata.normalize("NFKC", text or ""))}


def audit_claims(case: dict, resp, checker: PdfQuoteChecker) -> dict:
    """Independent re-check of every claim the system chose to show."""
    leaked, citations_total, citations_ok = [], 0, 0
    gold = gold_pairs(case)
    gold_hit = False
    for claim in resp.claims:
        reasons = []
        if claim.status != "supported":
            reasons.append(f"status={claim.status}")
        if not claim.citations:
            reasons.append("no_citation")
        quotes = []
        for cit in claim.citations:
            citations_total += 1
            ok = checker.verbatim(cit.doc_id, cit.page, cit.quote)
            citations_ok += int(ok)
            quotes.append(cit.quote)
            if not ok:
                reasons.append(f"quote_not_on_pdf_page:{cit.doc_id}:p{cit.page}")
            if (cit.doc_id, cit.page) in gold:
                gold_hit = True
        claim_en = claim.text_en or claim.text
        stray = numbers_in(claim_en) - numbers_in(" ".join(quotes))
        if claim.citations and stray:
            reasons.append(f"numbers_not_in_quotes:{sorted(stray)}")
        for bad in case.get("forbidden_values", []):
            if norm_value(bad) in norm_value(claim_en) or norm_value(bad) in norm_value(claim.text):
                reasons.append(f"forbidden_value:{bad}")
        if case["expect_abstention"]:
            reasons.append("shown_in_abstention_case")
        if reasons:
            leaked.append({"claim": claim.text_en or claim.text, "reasons": reasons})
    return {"shown": len(resp.claims), "leaked": leaked, "citations_total": citations_total,
            "citations_ok": citations_ok, "gold_page_cited": gold_hit}


def check_value(case: dict, resp) -> bool | None:
    expected = case.get("expected_value")
    if expected is None:
        return None
    haystack = " ".join([c.text for c in resp.claims] + [c.text_en or "" for c in resp.claims]
                        + ([resp.calculation.result] if resp.calculation else []))
    return all(norm_value(v) in norm_value(haystack) for v in ([expected] if isinstance(expected, str) else expected))


def judge_case(case: dict, resp, st, checker: PdfQuoteChecker, latency: float) -> dict:
    from app.amendments.graph import superseded_doc_ids

    exp_status = case["expected_status"]
    expected_docs = set(case["expected_doc_ids"])
    superseded = superseded_doc_ids(st.amendment_edges)
    audit = audit_claims(case, resp, checker)

    if exp_status == "clarification_needed":
        status_ok = resp.clarification_needed is not None
        abstention_ok = status_ok and resp.calculation is None  # asked instead of guessing a number
    elif case["expect_abstention"]:
        status_ok = resp.status == "abstained"
        abstention_ok = status_ok and not resp.claims
    else:
        status_ok = resp.status == exp_status
        abstention_ok = resp.status != "abstained" and (bool(resp.claims) or resp.calculation is not None)

    ctr_docs = [{v.doc_id for v in c.values} for c in resp.contradictions]
    predicted = bool(ctr_docs)
    strict_tp = case["expect_contradiction"] and any(len(d) >= 2 and d <= expected_docs for d in ctr_docs)
    superseded_fp = any(d & superseded for d in ctr_docs)

    active_ok = None
    if case["expected_active_doc"]:
        exp = case["expected_active_doc"]
        chain_ok = any(ch.active_doc_id == exp for ch in resp.amendment_chains)
        cited = any(cit.doc_id == exp for c in resp.claims for cit in c.citations)
        active_ok = chain_ok and cited

    missing_ok = None
    if case.get("expected_missing_keywords"):
        blob = " ".join(resp.missing_evidence).lower()
        missing_ok = all(k.lower() in blob for k in case["expected_missing_keywords"])

    return {
        "id": case["id"], "corpus": case["corpus"], "category": case["category"], "language": case["language"],
        "question": case["question"], "latency_s": round(latency, 2),
        "status": resp.status, "expected_status": exp_status, "status_ok": status_ok, "abstention_ok": abstention_ok,
        "expect_contradiction": case["expect_contradiction"], "contradiction_reported": predicted,
        "contradiction_strict_tp": bool(strict_tp), "superseded_contradiction": superseded_fp,
        "contradictions": [sorted(d) for d in ctr_docs],
        "expected_active_doc": case["expected_active_doc"], "amendment_resolution_ok": active_ok,
        "chain_active_docs": sorted({ch.active_doc_id for ch in resp.amendment_chains if ch.active_doc_id}),
        "expected_value_ok": check_value(case, resp), "missing_evidence_ok": missing_ok,
        "forbidden_value_hit": any(any(r.startswith("forbidden_value") for r in lk["reasons"]) for lk in audit["leaked"]),
        "faithfulness_pct": resp.faithfulness_pct, "verified_sentences": resp.verified_sentences_count,
        "total_shown_sentences": resp.total_shown_sentences, "drafted_claims": resp.drafted_claims_count,
        "blocked_claims": resp.blocked_claims_count, "claims_shown": audit["shown"],
        "citations_total": audit["citations_total"], "citations_verbatim_on_pdf_page": audit["citations_ok"],
        "gold_page_cited": audit["gold_page_cited"], "leaked_claims": audit["leaked"],
        "calculation_result": resp.calculation.result if resp.calculation else None,
        "clarification_requested": resp.clarification_needed is not None,
        "claims": [{"text": c.text_en or c.text, "citations": [f"{x.doc_name} p.{x.page}" for x in c.citations]} for c in resp.claims],
        "missing_evidence": resp.missing_evidence[:4],
    }


def aggregate_full(rows: list[dict]) -> dict:
    n = len(rows)
    shown = sum(r["claims_shown"] for r in rows)
    leaked = sum(len(r["leaked_claims"]) for r in rows)
    cit_total = sum(r["citations_total"] for r in rows)
    cit_ok = sum(r["citations_verbatim_on_pdf_page"] for r in rows)
    verified, total_sent = sum(r["verified_sentences"] for r in rows), sum(r["total_shown_sentences"] for r in rows)
    tp = sum(r["contradiction_strict_tp"] for r in rows)
    fp = sum(1 for r in rows if r["contradiction_reported"] and not r["contradiction_strict_tp"])
    fn = sum(1 for r in rows if r["expect_contradiction"] and not r["contradiction_strict_tp"])
    precision, recall = (tp / (tp + fp) if tp + fp else None), (tp / (tp + fn) if tp + fn else None)
    neg_controls = [r for r in rows if not r["expect_contradiction"] and r["expected_active_doc"]]
    active = [r for r in rows if r["expected_active_doc"]]
    abstain_cases = [r for r in rows if r["expected_status"] == "abstained"]
    answerable = [r for r in rows if r["expected_status"] not in ("abstained", "clarification_needed")]
    valued = [r for r in rows if r["expected_value_ok"] is not None]
    lat = sorted(r["latency_s"] for r in rows)
    drafted = sum(r["drafted_claims"] for r in rows)
    return {
        "cases": n,
        "faithfulness_pct": pct(verified, total_sent),
        "faithfulness_basis": f"{verified}/{total_sent} shown answer sentences backed by a verified source quote (pipeline-reported, pooled)",
        "hallucination_leakage_pct": pct(leaked, shown),
        "hallucination_leakage_basis": f"{leaked}/{shown} shown claims failed the independent audit (uncited, quote absent from the PDF page, "
                                       "number not in quote, forbidden value, or shown where the right answer is a refusal)",
        "citation_exact_match_pct": pct(cit_ok, cit_total),
        "citation_exact_match_basis": f"{cit_ok}/{cit_total} citations whose quote re-appears verbatim on the cited PDF page (re-read with PyMuPDF)",
        "abstention_accuracy_pct": pct(sum(r["abstention_ok"] for r in rows), n),
        "abstention_correct_refusals": f"{sum(r['abstention_ok'] for r in abstain_cases)}/{len(abstain_cases)}",
        "abstention_false_refusals": f"{sum(r['status'] == 'abstained' for r in answerable)}/{len(answerable)}",
        "contradiction": {"precision_pct": None if precision is None else round(100 * precision, 1),
                          "recall_pct": None if recall is None else round(100 * recall, 1), "tp": tp, "fp": fp, "fn": fn,
                          "definition": "case-level; TP needs a reported conflict whose >=2 docs are all gold evidence docs"},
        "superseded_false_positive_rate_pct": pct(sum(r["superseded_contradiction"] for r in neg_controls), len(neg_controls)),
        "superseded_fp_basis": f"{sum(r['superseded_contradiction'] for r in neg_controls)}/{len(neg_controls)} negative-control cases "
                               "(amendment-explained differences) that were wrongly raised as a conflict",
        "amendment_resolution_accuracy_pct": pct(sum(bool(r["amendment_resolution_ok"]) for r in active), len(active)),
        "amendment_resolution_basis": f"{sum(bool(r['amendment_resolution_ok']) for r in active)}/{len(active)} cases: chain active doc == gold "
                                      "and the answer cites it",
        "latency_s": {"median": round(statistics.median(lat), 1), "p95": round(lat[min(n - 1, int(0.95 * n))], 1),
                      "mean": round(statistics.mean(lat), 1), "min": lat[0], "max": lat[-1]},
        "supplementary": {
            "status_match_pct": pct(sum(r["status_ok"] for r in rows), n),
            "expected_value_hit_pct": pct(sum(bool(r["expected_value_ok"]) for r in valued), len(valued)),
            "gold_page_cited_pct": pct(sum(r["gold_page_cited"] for r in answerable), len(answerable)),
            "drafted_claims": drafted, "shown_claims": shown, "blocked_claims_count": sum(r["blocked_claims"] for r in rows),
            "draft_support_pct": pct(shown, drafted),
            "partial_proof_missing_flagged": [r["missing_evidence_ok"] for r in rows if r["missing_evidence_ok"] is not None],
        },
    }


def run_full(dataset: dict, names: list[str], only: list[str] | None) -> dict:
    from app.contradictions.detector import scan_corpus_contradictions
    from app.qa.service import ask_question

    t_start = time.perf_counter()
    stores, pdf_paths, skipped = build_corpora(dataset, names)
    cases = select_cases(dataset, stores, only)
    if not cases:
        raise SystemExit("No evaluable cases (check --corpora / missing PDFs).")
    checker = PdfQuoteChecker(pdf_paths)

    t_warm = time.perf_counter()
    first = stores[cases[0]["corpus"]]
    ask_question("What is the interest rate?", app_store=first)  # loads reranker + NLI + LLM; excluded from latency stats
    warm_s = time.perf_counter() - t_warm
    log(f"[warm-up] models loaded in {warm_s:.1f}s (excluded from latency)")

    rows = []
    for i, case in enumerate(cases, 1):
        st = stores[case["corpus"]]
        t0 = time.perf_counter()
        resp = ask_question(case["question"], app_store=st)
        row = judge_case(case, resp, st, checker, time.perf_counter() - t0)
        rows.append(row)
        flag = "ok " if row["status_ok"] and row["abstention_ok"] and not row["leaked_claims"] else "!! "
        log(f"[{i:>2}/{len(cases)}] {flag}{case['id']} {case['category']:<32} status={row['status']:<18} "
            f"(want {row['expected_status']}) {row['latency_s']:>5.1f}s leaked={len(row['leaked_claims'])}")

    corpus_scan = {}
    for name, st in stores.items():
        found = scan_corpus_contradictions(st)
        sup = {e.to_doc_id for e in st.amendment_edges}
        corpus_scan[name] = {"reported_conflicts": [c.subject for c in found],
                             "involving_superseded_docs": sum(1 for c in found if {v.doc_id for v in c.values} & sup)}
    return {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "corpora_evaluated": sorted(stores), "corpora_skipped": skipped,
        "metrics": aggregate_full(rows),
        "corpus_scan": corpus_scan,
        "warmup_s": round(warm_s, 1), "total_s": round(time.perf_counter() - t_start, 1),
        "per_case": rows,
    }


# ------------------------------------------------------------------------------------------------ markdown + report
def markdown_retrieval(sec: dict) -> str:
    lines = [f"**Retrieval ablation** - {sec['cases_scored']} labelled questions "
             f"({', '.join(sec['corpora_evaluated'])}), top-{sec['k']}, zero LLM calls\n",
             "| Retrieval mode | Recall@5 | Precision@5 | MRR@5 |", "|---|---|---|---|"]
    for mode, label in MODES:
        m = sec["modes"][mode]
        bold = "**" if mode == "pipeline" else ""
        lines.append(f"| {bold}{label}{bold} | {bold}{m['recall_at_5'] * 100:.1f}%{bold} | {bold}{m['precision_at_5'] * 100:.1f}%{bold} | "
                     f"{bold}{m['mrr_at_5']:.3f}{bold} |")
    g = sec["gate1_abstention"]
    lines.append(f"\nGate-1 (pre-LLM) abstention: {g['abstain_expected_caught']}/{g['abstain_expected']} no-proof questions refused before "
                 f"generation; {g['answerable_wrongly_abstained']}/{g['answerable']} answerable questions wrongly refused.")
    corp = sorted(sec["modes"]["pipeline"]["by_corpus"])
    if len(corp) > 1:
        lines += ["", "| Recall@5 by corpus | " + " | ".join(f"{c} (n={sec['modes']['pipeline']['by_corpus'][c]['n_cases']})" for c in corp) + " |",
                  "|---|" + "---|" * len(corp)]
        for mode, label in MODES:
            lines.append(f"| {label} | " + " | ".join(f"{sec['modes'][mode]['by_corpus'][c]['recall_at_5'] * 100:.1f}%" for c in corp) + " |")
    return "\n".join(lines)


def markdown_full(sec: dict) -> str:
    m = sec["metrics"]
    c = m["contradiction"]
    rows = [
        ("Faithfulness (shown sentences backed by a verified quote)", fmt_pct(m["faithfulness_pct"])),
        ("Hallucination leakage (independent audit, lower is better)", fmt_pct(m["hallucination_leakage_pct"])),
        ("Citation exact-match (quote verbatim on cited PDF page)", fmt_pct(m["citation_exact_match_pct"])),
        ("Abstention accuracy (refuse when no proof / answer when proof)", fmt_pct(m["abstention_accuracy_pct"])),
        ("Contradiction precision", fmt_pct(c["precision_pct"])),
        ("Contradiction recall", fmt_pct(c["recall_pct"])),
        ("Superseded false-positive rate (lower is better)", fmt_pct(m["superseded_false_positive_rate_pct"])),
        ("Amendment-resolution accuracy", fmt_pct(m["amendment_resolution_accuracy_pct"])),
        ("Latency, median / p95 per question", f"{m['latency_s']['median']:.1f} s / {m['latency_s']['p95']:.1f} s"),
    ]
    out = [f"**End-to-end pipeline** - {m['cases']} questions ({', '.join(sec['corpora_evaluated'])}), real local models, one in-process run\n",
           "| Metric | Result |", "|---|---|"]
    out += [f"| {k} | {v} |" for k, v in rows]
    s = m["supplementary"]
    out.append(f"\nSupporting counts: {m['faithfulness_basis']}; {m['hallucination_leakage_basis']}; {m['citation_exact_match_basis']}; "
               f"{m['superseded_fp_basis']}; {m['amendment_resolution_basis']}. Correct refusals {m['abstention_correct_refusals']}, "
               f"false refusals {m['abstention_false_refusals']}. Contradictions TP/FP/FN = {c['tp']}/{c['fp']}/{c['fn']}. "
               f"Expected-value hit {fmt_pct(s['expected_value_hit_pct'])}, status match {fmt_pct(s['status_match_pct'])}, "
               f"{s['drafted_claims']} drafted -> {s['shown_claims']} shown, {s['blocked_claims_count']} blocked.")
    failing = [r for r in sec["per_case"] if not (r["status_ok"] and r["abstention_ok"]) or r["leaked_claims"]]
    if failing:
        out.append("\nCases that missed a label: " + "; ".join(
            f"{r['id']} ({r['category']}: got {r['status']}, want {r['expected_status']}"
            + (f", {len(r['leaked_claims'])} leaked" if r["leaked_claims"] else "") + ")" for r in failing))
    return "\n".join(out)


def write_report(path: Path, section: str, payload: dict, env: dict) -> dict:
    report = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    report["environment"] = env
    report[section] = payload
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    md = [f"<!-- generated by backend/scripts/evaluate.py - dataset {env['dataset']['sha256_16']} @ {env.get('git_commit')} -->"]
    if "retrieval_ablation" in report:
        md.append(markdown_retrieval(report["retrieval_ablation"]))
    if "full_pipeline" in report:
        md.append(markdown_full(report["full_pipeline"]))
    path.with_suffix(".md").write_text("\n\n".join(md) + "\n", encoding="utf-8")
    return report


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--retrieval-only", action="store_true", help="4-way retrieval ablation, zero LLM calls")
    mode.add_argument("--full", action="store_true", help="end-to-end pipeline metrics with real local models")
    ap.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    ap.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    ap.add_argument("--corpora", default=None, help="comma list or 'all' (default: all for --retrieval-only, acme,rbi for --full)")
    ap.add_argument("--cases", default=None, help="comma list of case ids (debugging; implies --no-write)")
    ap.add_argument("--no-write", action="store_true", help="print only; do not touch the report files")
    args = ap.parse_args(argv)

    dataset = load_dataset(args.dataset)
    all_corpora = list(dataset["_meta"]["corpora"])
    default = all_corpora if args.retrieval_only else ["acme", "rbi"]
    names = all_corpora if args.corpora == "all" else ([c.strip() for c in args.corpora.split(",")] if args.corpora else default)
    only = [c.strip() for c in args.cases.split(",")] if args.cases else None

    tmp = isolate_side_effects()
    log(f"[eval] mode={'retrieval-only' if args.retrieval_only else 'full'} corpora={names} scratch={tmp}")
    if args.retrieval_only:
        section, payload = "retrieval_ablation", run_retrieval_only(dataset, names, only)
        md = markdown_retrieval(payload)
    else:
        section, payload = "full_pipeline", run_full(dataset, names, only)
        md = markdown_full(payload)

    print("\n" + md + "\n")
    if args.no_write or only:
        log("[eval] report not written (--no-write / --cases)")
    else:
        write_report(args.report, section, payload, environment(dataset, args.dataset))
        log(f"[eval] wrote {args.report} (+ .md)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
