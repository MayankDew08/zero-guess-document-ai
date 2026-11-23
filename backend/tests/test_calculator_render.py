from __future__ import annotations

from decimal import Decimal
from urllib.parse import quote

from fastapi.testclient import TestClient

import app.main as main
from app.calculator.service import calculate, is_calculation_query, parse_amount, parse_months
from tests.helpers import sample_store

Q = "Calculate the late payment penalty on an overdue EMI of Rs 50,000 for 2 months under the latest active rule."


def test_query_parsing():
    assert is_calculation_query(Q)
    assert not is_calculation_query("What is the late payment fee according to the latest active rule?")
    assert parse_amount(Q) == Decimal("50000")
    assert parse_months(Q) == Decimal("2")


def test_late_fee_uses_active_v3_rate_and_exact_math():
    st = sample_store()
    calc, missing = calculate(Q, st)
    assert missing == [] and calc is not None
    assert calc.kind == "late_payment_fee"
    assert calc.result == "Rs 2,000" and calc.result_value == 2000.0
    assert calc.inputs["rate_percent"] == 2.0 and calc.inputs["overdue_amount"] == 50000.0
    assert "Acme_Loan_Policy_v3.pdf" in calc.inputs["source"]  # active rule, not the 5% notice nor the 1% v1
    assert calc.citation and calc.citation.doc_name == "Acme_Loan_Policy_v3.pdf"
    stored = st.get_sentence(calc.citation.sentence_id)
    assert stored and calc.citation.quote == stored["text"]
    assert any("Rs 1,000" in s for s in calc.steps) and any("Rs 2,000" in s for s in calc.steps)


def test_interest_and_emi_math():
    st = sample_store()
    calc, _ = calculate("Calculate the interest on Rs 100000 for 12 months", st)
    assert calc is not None and calc.kind == "interest"  # "calculate" must not trigger the late-fee path
    assert calc.result == "Rs 7,000"  # 7% p.a. (v3), simple
    emi, _ = calculate("Calculate the EMI for a loan of Rs 100000 for 12 months", st)
    assert emi is not None and emi.kind == "emi" and abs(emi.result_value - 8652.67) < 0.01  # 7% p.a., 12 instalments


def test_missing_inputs_are_reported_not_guessed():
    st = sample_store()
    calc, missing = calculate("Calculate the late fee on Rs 50,000", st)
    assert calc is None and missing


def test_render_endpoint_returns_png_with_highlight(monkeypatch):
    st = sample_store()
    monkeypatch.setattr(main, "store", st)
    client = TestClient(main.app)  # no lifespan: no model loading
    plain = client.get("/api/documents/acme_loan_policy_v3/page/1/render")
    assert plain.status_code == 200 and plain.headers["content-type"] == "image/png"
    assert plain.content[:8] == b"\x89PNG\r\n\x1a\n"
    sid = next(s.sentence_id for c in st.all_chunks() if c.doc_id == "acme_loan_policy_v3"
               for s in c.sentences if "grace period of 15 days" in s.text)
    hl = client.get(f"/api/documents/acme_loan_policy_v3/page/1/render?sentence_id={quote(sid)}")
    assert hl.status_code == 200 and hl.headers["content-type"] == "image/png"
    assert hl.content != plain.content  # highlight actually drawn
    by_bbox = client.get("/api/documents/acme_loan_policy_v3/page/1/render?bbox=60,250,500,270")
    assert by_bbox.status_code == 200 and by_bbox.content != plain.content
    assert client.get("/api/documents/acme_loan_policy_v3/page/9/render").status_code == 400
    assert client.get("/api/documents/nope/page/1/render").status_code == 404


def test_contradictions_endpoint(monkeypatch):
    st = sample_store()
    monkeypatch.setattr(main, "store", st)
    monkeypatch.setattr(main.settings, "enable_nli", False)
    data = TestClient(main.app).get("/api/contradictions").json()
    assert data["count"] == 2
    assert {c["subject"] for c in data["contradictions"]} == {"late payment fee", "grace period"}
