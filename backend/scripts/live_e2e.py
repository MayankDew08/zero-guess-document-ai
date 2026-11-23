#!/usr/bin/env python3
"""Live end-to-end check against a RUNNING backend (real Ollama/bge-m3/reranker/mDeBERTa).

    uvicorn app.main:app --port 8001 &
    python scripts/live_e2e.py http://127.0.0.1:8001
"""
from __future__ import annotations

import json
import sys
import time

import httpx

BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8001").rstrip("/")

QUESTIONS = [
    ("1 Active Rule", "What is the late payment fee according to the latest active rule?"),
    ("2 Contradiction", "Are there any conflicting rules on late payment fees or grace periods?"),
    ("3 Multi-page+Table", "What are the processing fees, bounce charges, and borrower eligibility conditions in the latest policy?"),
    ("4 Calculation", "Calculate the late payment penalty on an overdue EMI of Rs 50,000 for 2 months under the latest active rule."),
    ("5 Hindi", "नवीनतम सक्रिय नियम के अनुसार विलंब भुगतान शुल्क (late payment fee) क्या है?"),
    ("6 Abstention", "What is the policy on cryptocurrency collateral for personal loans?"),
]


def main() -> int:
    c = httpx.Client(base_url=BASE, timeout=600.0)
    print("health:", json.dumps(c.get("/api/health").json()))

    t = time.time()
    ing = c.post("/api/ingest/samples").json()
    print(f"\n== INGEST ({time.time()-t:.1f}s) docs={len(ing['documents'])} chunks={ing['total_chunks']} "
          f"table_chunks={ing['table_chunks']} errors/warnings={ing['errors']}")
    for d in ing["documents"]:
        print(f"   {d['doc_name']}: pages={d['num_pages']} chunks={d['chunks_created']}")
    for e in ing["amendment_edges"]:
        print(f"   EDGE {e['from_doc_name']} {e['relation']} {e['to_doc_name']} :: “{e['evidence_quote']}”")

    t = time.time()
    ctr = c.get("/api/contradictions").json()
    print(f"\n== GET /api/contradictions ({time.time()-t:.1f}s) count={ctr['count']}")
    for x in ctr["contradictions"]:
        print(f"   [{x['subject']}] {x['explanation']}")
        for v in x["values"]:
            print(f"      {v['doc_name']} p.{v['page']}: “{v['quote']}”")
    bad = [x for x in ctr["contradictions"] if {v["doc_name"] for v in x["values"]} & {"Acme_Loan_Policy_v1.pdf", "Acme_Loan_Policy_v2.pdf"}]
    print("   false v1/v2-vs-v3 conflicts:", len(bad))

    rc = 0
    for label, q in QUESTIONS:
        t = time.time()
        r = c.post("/api/ask", json={"question": q})
        dt = time.time() - t
        if r.status_code != 200:
            print(f"\n== Q{label}: HTTP {r.status_code} {r.text[:300]}")
            rc = 1
            continue
        d = r.json()
        print(f"\n== Q{label} :: {q}")
        print(f"   status={d['status']} latency_s={dt:.1f} faithfulness_pct={d['faithfulness_pct']} "
              f"blocked_claims_count={d['blocked_claims_count']} drafted={d['drafted_claims_count']} draft_support_pct={d['draft_support_pct']}")
        print(f"   answer: {d['answer']}")
        for cl in d["claims"]:
            for cit in cl["citations"]:
                print(f"   ✔ {cl['text']}\n       ↳ {cit['doc_name']} p.{cit['page']} [{cit['sentence_id']}] nli={cit['nli_label']}: “{cit['quote']}”")
        for b in d["blocked_claims"]:
            print(f"   ✖ BLOCKED {b['text']} — {b['reason']}")
        for x in d["contradictions"]:
            print(f"   ⚠ CONTRADICTION [{x['subject']}] " + " VS ".join(f"{v['doc_name']} p.{v['page']}: “{v['quote']}”" for v in x["values"]))
        for ch in d["amendment_chains"]:
            print(f"   ⛓ CHAIN {' -> '.join(ch['doc_names_ordered'])} active={ch['active_doc_name']}")
        if d.get("calculation"):
            k = d["calculation"]
            print(f"   🧮 {k['formula']}\n      inputs={k['inputs']}")
            for s in k["steps"]:
                print("      -", s)
            print(f"      RESULT {k['result']}")
        if d["missing_evidence"]:
            print("   missing_evidence:", d["missing_evidence"][:3])

    r = c.get("/api/documents/acme_loan_policy_v3/page/1/render")
    print(f"\n== RENDER page 1: HTTP {r.status_code} {r.headers.get('content-type')} {len(r.content)} bytes")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
