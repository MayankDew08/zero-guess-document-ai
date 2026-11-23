#!/usr/bin/env python3
"""Live check on a real multi-section PDF (default: the Hackasol 5.0 problem statement).

    python scripts/live_real_pdf.py http://127.0.0.1:8001 [path/to.pdf]

Clears the corpus, uploads the PDF, asks the AIML-02 bonus-features / 1st-prize question (EN + HI) and checks
that the cited bonus features come from AIML-02 (page 6), faithfulness is 100%, the unproven prize money is in
missing_evidence (never invented) and the cited page renders with a highlight.
"""
from __future__ import annotations

import re
import sys
import time
from pathlib import Path
from urllib.parse import quote

import httpx

BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8001").rstrip("/")
PDF = Path(sys.argv[2] if len(sys.argv) > 2 else Path(__file__).resolve().parents[2] / "data" / "uploads" / "Hackasol_5.0_Problem_Statement.pdf")
QS = [
    ("EN", "What are the bonus features for AIML-02 and what is the 1st place prize money?"),
    ("HI", "AIML-02 की बोनस सुविधाएँ (bonus features) क्या हैं और प्रथम स्थान की पुरस्कार राशि (1st place prize money) कितनी है?"),
]
FAILS: list[str] = []


def check(ok: bool, msg: str) -> str:
    if not ok:
        FAILS.append(msg)
    return "PASS" if ok else "FAIL"


def main() -> int:
    c = httpx.Client(base_url=BASE, timeout=900)
    c.delete("/api/documents")
    t = time.time()
    r = c.post("/api/ingest", files=[("files", (PDF.name, PDF.read_bytes(), "application/pdf"))]).json()
    summ = c.get("/api/documents").json()["summary"]
    print(f"INGEST {PDF.name} ({time.time() - t:.1f}s): errors={r['errors']} summary={summ}")
    check(not r["errors"] and summ["chunks"] > 20, "ingest")
    for lang, q in QS:
        t = time.time()
        d = c.post("/api/ask", json={"question": q}).json()
        dt = time.time() - t
        print(f"\n== {lang} :: {q}\n   status={d['status']} latency_s={dt:.1f} faithfulness_pct={d['faithfulness_pct']} blocked={d['blocked_claims_count']} drafted={d['drafted_claims_count']}")
        for cl in d["claims"]:
            for cit in cl["citations"]:
                print(f"   ✔ {cl['text']}\n       ↳ p.{cit['page']} [{cit['section_context']}] nli={cit['nli_label']}: “{cit['quote'][:140]}”")
        for b in d["blocked_claims"]:
            print(f"   ✖ BLOCKED {b['text']} — {b['reason']}")
        print("   missing_evidence:", d["missing_evidence"])
        cits = [cit for cl in d["claims"] for cit in cl["citations"]]
        miss = " ".join(d["missing_evidence"]).lower()
        right = bool(cits) and all(cit["page"] == 6 and "AIML-02" in (cit["section_context"] or "") for cit in cits)
        invented = re.search(r"(prize|place)[^.]*(₹|rs\.?|inr|\$)\s*\d", " ".join(cl["text"] for cl in d["claims"]).lower())
        print("   checks:", check(right, f"{lang}: cites page 6 / AIML-02 only"), check(d["faithfulness_pct"] == 100.0, f"{lang}: faithfulness"),
              check(("prize" in miss or "पुरस्कार" in miss or "1st" in miss or "first" in miss) and not invented, f"{lang}: prize in missing_evidence, none invented"))
        if cits:
            cit = cits[0]
            plain = c.get(f"/api/documents/{cit['doc_id']}/page/{cit['page']}/render")
            hl = c.get(f"/api/documents/{cit['doc_id']}/page/{cit['page']}/render?sentence_id={quote(cit['sentence_id'])}")
            print(f"   render p.{cit['page']}: HTTP {hl.status_code} {hl.headers['content-type']} highlighted={hl.content != plain.content}",
                  check(hl.status_code == 200 and hl.content != plain.content, f"{lang}: highlight render"))
    print("\nFAILED CHECKS:", FAILS or "none")
    return 1 if FAILS else 0


if __name__ == "__main__":
    raise SystemExit(main())
