#!/usr/bin/env python3
"""Final live checks against ONE running backend (real models): Preset #8 two-turn flow, BYO isolation,
and the three real RBI circulars in byo_private.   python scripts/live_final.py http://127.0.0.1:8000"""
from __future__ import annotations

import sys
from pathlib import Path

import httpx

BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000").rstrip("/")
DOCS = Path(__file__).resolve().parents[2] / "data" / "documents"
FAILS: list[str] = []
c = httpx.Client(base_url=BASE, timeout=900.0)


def check(ok: bool, msg: str) -> str:
    if not ok:
        FAILS.append(msg)
    print(f"   [{'PASS' if ok else 'FAIL'}] {msg}")
    return "PASS" if ok else "FAIL"


def ask(q, ws="bank_official", history=None):
    r = c.post("/api/ask", json={"question": q, "workspace": ws, "history": history or []})
    r.raise_for_status()
    d = r.json()
    print(f"   status={d['status']} faith={d['faithfulness_pct']} blocked={d['blocked_claims_count']}")
    for cl in d["claims"]:
        ct = cl["citations"][0]
        print(f"     ✔ {cl['text']}  ↳ {ct['doc_name'][:14]} p.{ct['page']} nli={ct['nli_label']}")
    return d


def main() -> int:
    print("== PRESET #8 two-turn (bank_official)")
    q1 = "Calculate my late payment penalty under the latest active rule."
    t1 = ask(q1)
    cl = t1.get("clarification_needed")
    check(bool(cl) and [f["key"] for f in cl["missing_fields"]] == ["principal", "months"] and t1["calculation"] is None, "turn 1: clarification_needed, nothing guessed")
    check(any("2%" in x["text"] for x in t1["claims"]) and t1["faithfulness_pct"] == 100.0, "turn 1: verified 2% per month at 100% faithfulness")
    hist = [{"role": "user", "question": q1, "answer_summary": t1["answer"][:300], "pending_calculation": cl["pending_calculation"] if cl else None}]
    t2 = ask("Rs 50,000 for 2 months", history=hist)
    check((t2["calculation"] or {}).get("result") == "Rs 2,000" and t2["faithfulness_pct"] == 100.0, "turn 2: Rs 2,000 at 100% faithfulness")
    print("   resolved:", t2.get("rewritten_question"))

    print("\n== BYO isolation")
    before = c.get("/api/documents?workspace=bank_official").json()["summary"]
    for d in c.get("/api/documents?workspace=byo_private").json()["documents"]:
        c.delete(f"/api/documents/{d['doc_id']}?workspace=byo_private")
    files = [("files", (p.name, p.read_bytes(), "application/pdf")) for p in sorted(DOCS.glob("*.pdf")) if p.name[:4] in ("FAIR", "NOTI", "PENA")]
    check(len(files) == 3, "3 RBI PDFs found in data/documents")
    ing = c.post("/api/ingest?workspace=byo_private", files=files).json()
    check(not ing["errors"] and len(ing["documents"]) == 3, "RBI PDFs ingested into byo_private")
    after = c.get("/api/documents?workspace=bank_official").json()["summary"]
    check(after["documents"] == before["documents"] and after["chunks"] == before["chunks"], f"bank_official unchanged ({after['documents']} docs / {after['chunks']} chunks)")
    names = {d["doc_name"] for d in c.get("/api/documents?workspace=bank_official").json()["documents"]}
    check(not any(n.startswith(("FAIR", "NOTI", "PENA")) for n in names), "no RBI doc visible in bank_official")
    leak = ask("What is the late payment fee according to the latest active rule?")
    check(not any("RBI" in x["citations"][0]["doc_name"] or "PENAL" in x["citations"][0]["doc_name"] for x in leak["claims"]), "bank query cites only bank docs")

    print("\n== RBI circulars (byo_private)")
    docs = c.get("/api/documents?workspace=byo_private").json()["documents"]
    by = {d["doc_name"][:4]: d for d in docs}
    check("DoR.MCS.REC.61/01.01.001/2023-24" in by["PENA"]["aliases"] and "DoR.MCS.REC.28/01.01.001/2023-24" in by["FAIR"]["aliases"], "aliases extracted (REC.61, REC.28)")
    qa = ask("What is the current Penal Charges in Loan Accounts?", "byo_private")
    ch = qa["amendment_chains"]
    e = ch[0]["edges"][0] if ch and ch[0]["edges"] else None
    check(bool(qa["claims"]) and qa["faithfulness_pct"] == 100.0 and "invalid JSON" not in " ".join(qa["missing_evidence"]), "Q1: verified claims, 100% faithfulness, no invalid JSON")
    check(bool(e) and e["from_doc_name"].startswith("PENA") and e["to_doc_name"].startswith("FAIR") and e["relation"] == "AMENDS" and ch[0]["active_doc_name"].startswith("PENA"), "Q1: chain REC.28 -> REC.61 (AMENDS), REC.61 active")
    print("   edge quote:", e and e["evidence_quote"], "| effective", e and e["effective_date"])
    check(bool(e) and e["evidence_quote"].endswith("by three months.") and e["evidence_quote"].startswith("However, considering"), "edge quote is a FULL sentence")
    check(bool(e) and e["effective_date"] == "2024-04-01", "chain effective 2024-04-01")
    q2 = ask("When do the RBI Penal Charges in Loan Accounts instructions come into effect?", "byo_private")
    txt = " ".join(x["text"] for x in q2["claims"])
    check(q2["status"] != "abstained" and q2["faithfulness_pct"] == 100.0 and "April 1, 2024" in txt and "June 30, 2024" in txt, "Q2: April 1, 2024 / June 30, 2024 verified, 100%")
    q3 = ask("What is the compensation for delay in releasing property documents?", "byo_private")
    pay = next((x for x in q3["claims"] if "5,000" in x["text"]), None)
    check(bool(pay) and q3["faithfulness_pct"] == 100.0 and pay["citations"][0]["page"] == 2, "Q3: ₹5,000/- per day, Page 2, 100%")
    if pay:
        ct = pay["citations"][0]
        plain = c.get(f"/api/documents/{ct['doc_id']}/page/{ct['page']}/render?workspace=byo_private")
        hl = c.get(f"/api/documents/{ct['doc_id']}/page/{ct['page']}/render", params={"workspace": "byo_private", "sentence_id": ct["sentence_id"]})
        check(hl.status_code == 200 and hl.content[:8] == b"\x89PNG\r\n\x1a\n" and hl.content != plain.content, "Q3: highlight render is a valid PNG with a drawn highlight")
    print("\nFAILED CHECKS:", FAILS or "none")
    return 1 if FAILS else 0


if __name__ == "__main__":
    raise SystemExit(main())
