# Dataset and Evaluation Plan

You control the demo corpus. Build it to exercise every must-have.

## Corpus strategy

Use **digital, text-selectable PDFs** you generate yourself. Do not rely on scanned/OCR PDFs unless you implement OCR. Keep documents short (2-6 pages each) but realistic.

## Recommended sample corpus

Create 4-6 PDFs in `data/samples/`:

| File | Purpose | Key content |
|---|---|---|
| `Loan_Policy_2023.pdf` | Original rule | Late fee 1% per month; eligibility age >= 21; effective 2023-01-01 |
| `Loan_Policy_Amendment_2024.pdf` | Amendment B | "Amends Loan_Policy_2023.pdf"; late fee 1.5%; effective 2024-06-01 |
| `Loan_Policy_Amendment_2025.pdf` | Amendment C | "Amends Loan_Policy_Amendment_2024.pdf"; late fee 2%; effective 2025-04-01 |
| `Vendor_Contract_A.pdf` | Contradiction source | Service penalty INR 5,000 for missed SLA |
| `Vendor_Contract_B.pdf` | Contradiction source | Service penalty INR 2,000 for missed SLA for same service |
| `Regulatory_Circular.pdf` | Multi-doc/table question | Table of rates/fees; clause spanning pages |

## How to generate sample PDFs

Use Python + ReportLab or simple HTML->PDF. Keep generation script in `scripts/generate_samples.py` so corpus is reproducible.

```python
# scripts/generate_samples.py (sketch)
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

def make_pdf(path, pages):
    c = canvas.Canvas(path, pagesize=A4)
    for lines in pages:
        y = 800
        for line in lines:
            c.drawString(50, y, line)
            y -= 18
        c.showPage()
    c.save()
```

Include clear phrases for amendment detection: "This amendment supersedes..." / "amends..." / "effective from YYYY-MM-DD".

## Gold evaluation set

Create `data/eval/gold_qa.json` with 10-20 questions. Each entry:

```json
{
  "id": "Q1",
  "question": "What is the current late payment fee?",
  "expected_status": "answered",
  "expected_docs": ["Loan_Policy_Amendment_2025.pdf"],
  "expected_answer_contains": ["2% per month"],
  "expected_quotes": ["late payment fee is revised to 2% per month"],
  "expected_contradiction": false,
  "expected_amendment_chain": true,
  "expected_abstain": false
}
```

### Must-cover cases

| Case | Example question | Expected |
|---|---|---|
| Simple factual | "What is the late payment fee in Loan Policy 2023?" | Answered, citation to 2023 doc |
| Multi-doc | "Compare penalty clauses in Contract A and Contract B." | Cites both docs |
| Multi-page | "Summarize eligibility and fee rules." | Cites multiple pages/sections |
| Contradiction | "What is the service penalty for missed SLA?" | Contradiction side-by-side |
| Amendment chain | "Which late fee rule applies today?" | Current rule + A→B→C chain |
| Abstention | "What is the penalty for early closure?" | `I don't have proof...` |
| Partial evidence | Question where one claim supported, one missing | Partial answer + blocked claim/missing evidence |
| Table value | "What is the processing fee in the rate table?" | Citation to table chunk/page |

## Evaluation metrics

### Automatic checks (scriptable)

| Metric | How | Target |
|---|---|---|
| Citation presence | Verify every displayed quote is normalized substring in cited chunk/page | 100% |
| Citation metadata | Doc/page/chunk exists | 100% |
| Faithfulness computation | Supported sentences / total sentences matches manual count on sample | Correct |
| Abstention correctness | Out-of-corpus questions return abstained status | 100% on gold abstention set |
| Contradiction recall (demo set) | Known planted contradictions flagged | All planted cases |
| Amendment resolution (demo set) | Current rule matches latest effective amendment | All planted cases |

### Manual checks (judge/demo)

- Are quotes verbatim and readable?
- Is contradiction shown side by side clearly?
- Is amendment chain understandable?
- Does abstention clearly state what is missing?
- Is faithfulness score visible and plausible?

## Eval script sketch

```python
# scripts/eval_gold.py
import json, httpx

def main():
    gold = json.load(open("data/eval/gold_qa.json"))
    passed = 0
    for case in gold:
        r = httpx.post("http://localhost:8000/api/ask", json={"question": case["question"]}, timeout=120)
        data = r.json()
        ok = True
        if case["expected_abstain"] and data["status"] != "abstained":
            ok = False
        for s in case.get("expected_answer_contains", []):
            if s.lower() not in data.get("answer", "").lower():
                ok = False
        # verify citations
        for claim in data.get("claims", []):
            for cit in claim.get("citations", []):
                # optionally fetch chunk and verify quote
                pass
        print(case["id"], "PASS" if ok else "FAIL", data["status"])
        passed += int(ok)
    print(f"{passed}/{len(gold)} passed")

if __name__ == "__main__":
    main()
```

## Demo corpus rules

- Keep corpus small and clean for live demo.
- Pre-index before judging.
- Do not delete source PDFs after indexing; citations need them.
- Include at least one obvious contradiction and one obvious 3-doc amendment chain.
- Include one question with no answer in corpus.