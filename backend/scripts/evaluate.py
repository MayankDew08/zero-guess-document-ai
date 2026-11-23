#!/usr/bin/env python3
"""Evaluation on the clean 4-PDF sample corpus with the REAL local models
(Ollama qwen2.5:7b-instruct, bge-m3, bge-reranker-v2-m3, mDeBERTa NLI). No mocks.

Run from backend/:  python scripts/evaluate.py
Writes data/reports/evaluation_summary.json.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.contradictions.detector import scan_corpus_contradictions  # noqa: E402
from app.core.config import settings  # noqa: E402
from app.core.store import store  # noqa: E402
from app.ingestion.service import ingest_samples, rebuild_runtime_index  # noqa: E402
from app.qa.service import ask_question  # noqa: E402

# (label, question, expectations)
CASES = [
    ("active_rule", "What is the late payment fee according to the latest active rule?",
     {"claim_has": "2%", "claim_lacks": ["1%", "5%"], "chain_active": "Acme_Loan_Policy_v3.pdf"}),
    ("contradiction", "Are there any conflicting rules on late payment fees or grace periods?",
     {"contradiction_docs": {"Acme_Loan_Policy_v3.pdf", "Acme_Operations_Notice.pdf"}}),
    ("multipage_table", "What are the processing fees, bounce charges, and borrower eligibility conditions in the latest policy?",
     {"claim_has_all": ["INR 1,000", "INR 750", "700"]}),
    ("calculation", "Calculate the late payment penalty on an overdue EMI of Rs 50,000 for 2 months under the latest active rule.",
     {"calc_result": "Rs 2,000"}),
    ("hindi", "नवीनतम सक्रिय नियम के अनुसार विलंब भुगतान शुल्क (late payment fee) क्या है?",
     {"claim_has": "2%"}),
    ("abstention", "What is the policy on cryptocurrency collateral for personal loans?",
     {"status": "abstained"}),
]


def check(d: dict, exp: dict) -> list[str]:
    fails: list[str] = []
    texts = " ".join(c["text"] for c in d["claims"])
    if "claim_has" in exp and exp["claim_has"] not in texts:
        fails.append(f"no verified claim mentions {exp['claim_has']}")
    for bad in exp.get("claim_lacks", []):
        if bad in texts:
            fails.append(f"verified claims contain forbidden value {bad}")
    for need in exp.get("claim_has_all", []):
        if need not in texts:
            fails.append(f"missing verified claim with {need}")
    if "chain_active" in exp and not any(ch["active_doc_name"] == exp["chain_active"] for ch in d["amendment_chains"]):
        fails.append("amendment chain does not show v3 as active")
    if "contradiction_docs" in exp:
        got = [{v["doc_name"] for v in c["values"]} for c in d["contradictions"]]
        if exp["contradiction_docs"] not in got:
            fails.append("expected Ops Notice vs v3 contradiction not reported")
    if "calc_result" in exp and (d.get("calculation") or {}).get("result") != exp["calc_result"]:
        fails.append(f"calculation result != {exp['calc_result']}")
    if "status" in exp and d["status"] != exp["status"]:
        fails.append(f"status {d['status']} != {exp['status']}")
    for c in d["claims"]:  # every shown claim must be supported + cited
        if c["status"] != "supported" or not c["citations"]:
            fails.append(f"unsupported claim leaked into answer: {c['text']}")
    return fails


def main() -> int:
    print(f"providers: llm={settings.llm_provider}:{settings.ollama_model} emb={settings.embedding_provider}:{settings.embedding_model}"
          f"({settings.embedding_device}) rerank={settings.reranker_provider}({settings.reranker_device}) nli={settings.nli_provider}({settings.nli_device})")
    docs, errs = ingest_samples()
    rebuild_runtime_index()
    tables = sum(1 for c in store.chunks.values() if c.chunk_type == "table")
    print(f"Ingested {len(docs)} docs, warnings={errs}; chunks={len(store.chunks)} (table={tables})")
    corpus_ctr = scan_corpus_contradictions(store)
    false_v1_v3 = [c for c in corpus_ctr if {"Acme_Loan_Policy_v1.pdf", "Acme_Loan_Policy_v2.pdf"} & {v.doc_name for v in c.values}]
    print(f"Corpus contradictions: {[c.subject for c in corpus_ctr]}  false v1/v2-vs-v3: {len(false_v1_v3)}")

    totals = {"drafted": 0, "supported": 0, "blocked": 0}
    faith: list[float] = []
    results = []
    failures = 0
    for label, q, exp in CASES:
        t0 = time.time()
        d = ask_question(q).model_dump()
        dt = time.time() - t0
        fails = check(d, exp)
        failures += bool(fails)
        totals["drafted"] += d["drafted_claims_count"]
        totals["supported"] += len(d["claims"])
        totals["blocked"] += d["blocked_claims_count"]
        if d["faithfulness_pct"] is not None:
            faith.append(d["faithfulness_pct"])
        print(f"\n[{ 'PASS' if not fails else 'FAIL' }] {label}: status={d['status']} latency_s={dt:.1f} "
              f"faithfulness={d['faithfulness_pct']} blocked={d['blocked_claims_count']} claims={len(d['claims'])} "
              f"contradictions={len(d['contradictions'])}")
        for f in fails:
            print("   ✖", f)
        results.append({"case": label, "status": d["status"], "latency_s": round(dt, 1), "faithfulness_pct": d["faithfulness_pct"],
                        "blocked_claims_count": d["blocked_claims_count"], "verified_claims": len(d["claims"]),
                        "contradictions": len(d["contradictions"]), "failures": fails})

    summary = {
        "corpus": {"documents": len(docs), "chunks": len(store.chunks), "table_chunks": tables,
                   "corpus_contradictions": [c.subject for c in corpus_ctr], "false_v1_v3_conflicts": len(false_v1_v3)},
        "models": {"llm": settings.ollama_model, "embedding": settings.embedding_model,
                   "reranker": settings.reranker_model, "nli": settings.nli_model},
        "questions": len(CASES), "cases_failed": failures,
        "drafted_claims": totals["drafted"], "verified_claims_shown": totals["supported"],
        "blocked_claims_count": totals["blocked"],
        "avg_faithfulness_pct_of_shown": round(sum(faith) / len(faith), 1) if faith else None,
        "draft_support_pct": round(totals["supported"] / totals["drafted"] * 100, 1) if totals["drafted"] else None,
        "results": results,
    }
    print("\n=== SUMMARY ===")
    print(json.dumps({k: v for k, v in summary.items() if k != "results"}, indent=2))
    out = ROOT.parent / "data" / "reports" / "evaluation_summary.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(summary, indent=2, ensure_ascii=False))
    print(f"Wrote {out}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
