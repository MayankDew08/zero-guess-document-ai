#!/usr/bin/env python3
"""Live end-to-end check against a RUNNING backend (real Ollama / bge-m3 / reranker / mDeBERTa).

    uvicorn app.main:app --port 8001 &
    python scripts/live_e2e.py http://127.0.0.1:8001

Runs all 7 demo presets, verifies the Final-Eval requirements, prints a results table and writes
data/reports/live_e2e_results.json. Exit code 1 if any check fails.
"""
from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path
from urllib.parse import quote

import httpx

BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8001").rstrip("/")
DEV = re.compile(r"[ऀ-ॿ]")

PRESETS = [
    ("1 Active Rule", "What is the late payment fee according to the latest active rule?"),
    ("2 Contradiction", "Are there any conflicting rules on late payment fees or grace periods?"),
    ("3 Multi-Page & Fee Table", "What are the processing fees, bounce charges, and borrower eligibility conditions in the latest policy?"),
    ("4 Calculation", "Calculate the late payment penalty on an overdue EMI of Rs 50,000 for 2 months under the latest active rule."),
    ("5 Hindi", "नवीनतम सक्रिय नियम के अनुसार विलंब भुगतान शुल्क (late payment fee) क्या है?"),
    ("6 Abstention", "What is the policy on cryptocurrency collateral for personal loans?"),
    ("7 Partial Proof", "What is the late payment fee and what is the international SWIFT wire transfer fee under the latest active rule?"),
]

FAILS: list[str] = []


def check(ok: bool, msg: str) -> str:
    if not ok:
        FAILS.append(msg)
    return "PASS" if ok else "FAIL"


def main() -> int:
    c = httpx.Client(base_url=BASE, timeout=900.0)
    h = c.get("/api/health").json()
    print("health:", json.dumps(h))

    t = time.time()
    ing = c.post("/api/ingest/samples").json()
    print(f"\n== INGEST ({time.time() - t:.1f}s) docs={len(ing['documents'])} chunks={ing['total_chunks']} table_chunks={ing['table_chunks']} warnings={ing['errors']}")
    check(len(ing["documents"]) == 4 and ing["total_chunks"] > 15 and ing["table_chunks"] >= 1 and not ing["errors"], "ingest")

    ctr = c.get("/api/contradictions").json()
    print(f"== CONTRADICTIONS count={ctr['count']}: {[x['subject'] for x in ctr['contradictions']]}")
    check(ctr["count"] == 2, "contradictions endpoint")

    rows, results = [], []
    answers: dict[str, dict] = {}
    for label, q in PRESETS:
        t = time.time()
        r = c.post("/api/ask", json={"question": q})
        dt = time.time() - t
        if r.status_code != 200:
            print(f"\n== {label}: HTTP {r.status_code} {r.text[:200]}")
            check(False, f"{label} http")
            continue
        d = r.json()
        answers[label] = d
        print(f"\n== {label} :: {q}\n   status={d['status']} latency_s={dt:.1f} faithfulness_pct={d['faithfulness_pct']} blocked={d['blocked_claims_count']} draft_support={d['draft_support_pct']}")
        for cl in d["claims"]:
            cit = cl["citations"][0]
            print(f"   ✔ [{cl['language']}] {cl['text']}" + (f"\n       EN: {cl['text_en']}" if cl.get("text_en") else "") +
                  f"\n       ↳ {cit['doc_name']} p.{cit['page']} nli={cit['nli_label']}: “{cit['quote']}”")
        for b in d["blocked_claims"]:
            print(f"   ✖ BLOCKED {b['text']} — {b['reason']}")
        if d["missing_evidence"]:
            print("   missing_evidence:", d["missing_evidence"])
        if d.get("calculation"):
            print("   🧮", d["calculation"]["result"], d["calculation"]["steps"])
        tr = d["pipeline_trace"]
        print("   trace:", json.dumps(tr))
        check(tr is not None and set(tr) == {"gate1_retrieval", "gate2_citation_resolution", "gate3_nli_and_numeric", "gate4_lineage_and_conflicts"}, f"{label} trace")
        verdict = "n/a"
        texts = " ".join(x["text"] for x in d["claims"])
        if label.startswith("1"):
            verdict = check("2%" in texts and "Loan_Policy_v3" in d["claims"][0]["citations"][0]["doc_name"], "preset1")
        elif label.startswith("2"):
            verdict = check(len(d["contradictions"]) == 2, "preset2")
        elif label.startswith("3"):
            verdict = check(all(k in texts for k in ("1,000", "750", "700")), "preset3 claims")
        elif label.startswith("4"):
            verdict = check((d.get("calculation") or {}).get("result") == "Rs 2,000" and d["claims"], "preset4")
        elif label.startswith("5"):
            hi = [x for x in d["claims"] if DEV.search(x["text"])]
            ok = bool(hi) and len(hi) == len(d["claims"]) and d["faithfulness_pct"] == 100.0 and "2%" in texts \
                and all(x["citations"][0]["nli_label"] == "entailment" for x in hi)
            verdict = check(ok, "preset5 hindi")
        elif label.startswith("6"):
            verdict = check(d["status"] == "abstained" and d["answer"].lower().find("i don't have proof") >= 0 and not d["claims"], "preset6")
        elif label.startswith("7"):
            miss = " ".join(d["missing_evidence"]).lower()
            nums_in_swift = re.findall(r"swift[^.]*\d", " ".join(x["text"] for x in d["claims"]).lower())
            verdict = check("2%" in texts and "swift" in miss and not nums_in_swift and d["status"] != "abstained", "preset7")
        rows.append((label, d["status"], round(dt, 1), d["faithfulness_pct"], d["blocked_claims_count"], len(d["claims"]), len(d["contradictions"]), verdict))
        results.append({"preset": label, "status": d["status"], "latency_s": round(dt, 1), "faithfulness_pct": d["faithfulness_pct"],
                        "blocked_claims_count": d["blocked_claims_count"], "verified_claims": len(d["claims"]),
                        "contradictions": len(d["contradictions"]), "check": verdict})

    # table-citation render (preset 3)
    p3 = answers.get("3 Multi-Page & Fee Table")
    if p3:
        tc = next((cit for cl in p3["claims"] for cit in cl["citations"] if "|" in cit["quote"]), None)
        if tc:
            plain = c.get(f"/api/documents/{tc['doc_id']}/page/{tc['page']}/render")
            hl = c.get(f"/api/documents/{tc['doc_id']}/page/{tc['page']}/render?sentence_id={quote(tc['sentence_id'])}")
            ok = hl.status_code == 200 and hl.headers["content-type"] == "image/png" and hl.content != plain.content
            print(f"\n== TABLE CITATION RENDER {tc['sentence_id']}: HTTP {hl.status_code} {hl.headers['content-type']} {len(hl.content)}B highlighted={hl.content != plain.content} [{check(ok, 'table render')}]")
        else:
            check(False, "no table citation in preset 3")

    # audit report (preset 2: has contradictions + amendments)
    p2 = answers.get("2 Contradiction")
    if p2:
        rep = c.post("/api/report", json={"response": p2, "format": "html"}).json()
        html = c.get(rep["download_url"]).text
        quotes = [cl["citations"][0]["quote"] for cl in p2["claims"]] + [v["quote"] for x in p2["contradictions"] for v in x["values"]] \
            + [e["evidence_quote"] for ch in p2["amendment_chains"] for e in ch["edges"]]
        missing = [q for q in quotes if q not in html]
        print(f"== REPORT {rep['download_url']}: {len(html)} bytes; verbatim quotes checked={len(quotes)} missing={len(missing)} [{check(not missing and 'Quote A' in html and 'SUPERSEDES' in html, 'report')}]")

    # delete endpoints on a throw-away copy, then restore
    docs = c.get("/api/documents").json()["documents"]
    n = len(docs)
    d1 = c.delete(f"/api/documents/{docs[-1]['doc_id']}").json()
    ok1 = d1["summary"]["documents"] == n - 1
    d2 = c.delete("/api/documents").json()
    ok2 = d2["summary"]["documents"] == 0 and d2["summary"]["chunks"] == 0
    c.post("/api/ingest/samples")
    print(f"== DELETE one -> {d1['summary']['documents']} docs [{check(ok1, 'delete one')}]; CLEAR -> 0 docs [{check(ok2, 'clear all')}]; re-ingested.")

    r = c.get("/api/documents/acme_loan_policy_v3/page/1/render")
    print(f"== RENDER page 1: HTTP {r.status_code} {r.headers.get('content-type')} [{check(r.status_code == 200 and r.headers.get('content-type') == 'image/png', 'render')}]")

    print("\n| Preset | Status | Latency (s) | Faithfulness | Blocked | Verified claims | Conflicts | Check |\n|---|---|---|---|---|---|---|---|")
    for r_ in rows:
        print("| " + " | ".join(str(x) for x in r_) + " |")
    out = Path(__file__).resolve().parents[2] / "data" / "reports" / "live_e2e_results.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"base": BASE, "results": results, "failures": FAILS}, indent=2, ensure_ascii=False))
    print("\nFAILED CHECKS:", FAILS or "none")
    return 1 if FAILS else 0


if __name__ == "__main__":
    raise SystemExit(main())
