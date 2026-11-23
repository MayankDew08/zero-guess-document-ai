"""Generate the cohesive 4-PDF demo corpus in data/samples/.

  Acme_Loan_Policy_v1.pdf     2 pages  Jan 2023  5% interest, 1% late fee, 12-month tenure
  Acme_Loan_Policy_v2.pdf     2 pages  Jan 2024  supersedes v1: 6% / 2% / 24 months
  Acme_Loan_Policy_v3.pdf     3 pages  Jan 2025  supersedes v2: 7% / 2% / 36 months, fee table,
                                                 Eligibility clause spanning pages 2-3
  Acme_Operations_Notice.pdf  2 pages  Feb 2025  NO amendment link: 5% late fee, 5-day grace
                                                 (genuine unresolved conflict with v3)

Run from repo root:  python scripts/generate_samples.py
"""
from __future__ import annotations

from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "samples"

styles = getSampleStyleSheet()
H1, H2, N = styles["Heading1"], styles["Heading2"], styles["Normal"]
N.leading = 15

# Vertical gap that pushes the v3 Eligibility clause so items (a)-(c) sit on page 2 and
# items (d)-(f) continue on page 3. Verified by backend/tests/test_ingestion_parsing.py.
V3_ELIGIBILITY_SPACER_IN = 6.9


def _build(path: Path, story) -> None:
    d = SimpleDocTemplate(str(path), pagesize=LETTER, leftMargin=0.8 * inch, rightMargin=0.8 * inch,
                          title=path.stem.replace("_", " "), author="Acme Finance")
    d.build(story)


def _p(text: str) -> Paragraph:
    return Paragraph(text, N)


def _gap(h: float = 0.08) -> Spacer:
    return Spacer(1, h * inch)


def policy_v1(out: Path = OUT) -> Path:
    story = [
        Paragraph("Acme Loan Policy - Version 1", H1),
        _p("Effective Date: 1 January 2023"),
        _gap(0.15),
        _p("This policy sets out the standard terms for Acme personal loans offered to retail customers."),
        Paragraph("1. Interest Rate", H2),
        _p("The interest rate is 5% per year for all standard personal loans."),
        Paragraph("2. Late Payment Fee", H2),
        _p("A late payment fee of 1% per month applies after the due date."),
        Paragraph("3. Loan Tenure", H2),
        _p("The standard loan tenure is 12 months."),
        PageBreak(),
        Paragraph("4. Eligibility", H2),
        _p("Applicants must be between 21 and 60 years of age at the time of application."),
        _gap(),
        _p("Applicants must have a minimum credit score of 650 to qualify for a standard personal loan."),
        _gap(),
        _p("Applicants must provide salary slips for the last 3 months."),
        Paragraph("5. Prepayment", H2),
        _p("No prepayment penalty applies to standard personal loans."),
        Paragraph("6. Governing Law", H2),
        _p("This policy is governed by the laws of India."),
    ]
    path = out / "Acme_Loan_Policy_v1.pdf"
    _build(path, story)
    return path


def policy_v2(out: Path = OUT) -> Path:
    story = [
        Paragraph("Acme Loan Policy - Version 2", H1),
        _p("Effective Date: 1 January 2024"),
        _gap(0.15),
        _p("This policy sets out the standard terms for Acme personal loans offered to retail customers."),
        Paragraph("1. Interest Rate", H2),
        _p("The interest rate is 6% per year for all standard personal loans."),
        _gap(),
        _p("This policy supersedes and replaces Acme Loan Policy v1 with effect from 1 January 2024."),
        Paragraph("2. Late Payment Fee", H2),
        _p("A late payment fee of 2% per month applies after the due date."),
        Paragraph("3. Loan Tenure", H2),
        _p("The standard loan tenure is 24 months."),
        PageBreak(),
        Paragraph("4. Eligibility", H2),
        _p("Applicants must be between 21 and 60 years of age at the time of application."),
        _gap(),
        _p("Applicants must have a minimum credit score of 680 to qualify for a standard personal loan."),
        _gap(),
        _p("Applicants must provide salary slips for the last 3 months."),
        Paragraph("5. Prepayment", H2),
        _p("A prepayment penalty of 1% applies if the loan is closed within 6 months."),
        Paragraph("6. Governing Law", H2),
        _p("This policy is governed by the laws of India."),
    ]
    path = out / "Acme_Loan_Policy_v2.pdf"
    _build(path, story)
    return path


def policy_v3(out: Path = OUT, spacer_in: float = V3_ELIGIBILITY_SPACER_IN) -> Path:
    fee_rows = [
        ["Fee Type", "Amount", "When Applied"],
        ["Processing Fee", "INR 1,000", "At disbursement"],
        ["Prepayment Penalty", "2% of prepaid amount", "Within 12 months"],
        ["Bounce Charge", "INR 750 per bounced EMI", "On dishonour of an instalment"],
        ["Late Payment Fee", "2% per month", "After the grace period"],
    ]
    table = Table(fee_rows, colWidths=[1.9 * inch, 2.3 * inch, 2.5 * inch])
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
        ("GRID", (0, 0), (-1, -1), 0.6, colors.grey),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    story = [
        Paragraph("Acme Loan Policy - Version 3", H1),
        _p("Effective Date: 1 January 2025"),
        _gap(0.15),
        _p("This policy sets out the standard terms for Acme personal loans offered to retail customers."),
        Paragraph("1. Interest Rate", H2),
        _p("The interest rate is 7% per year for all standard personal loans."),
        _gap(),
        _p("This policy supersedes Acme Loan Policy v2 with effect from 1 January 2025."),
        Paragraph("2. Late Payment Fee and Grace Period", H2),
        _p("A late payment fee of 2% per month applies on the overdue amount after the grace period."),
        _gap(),
        _p("A grace period of 15 days applies after the due date before any late payment fee is charged."),
        Paragraph("3. Fees and Charges", H2),
        table,
        PageBreak(),
        Paragraph("4. Loan Tenure", H2),
        _p("The standard loan tenure is 36 months."),
        Spacer(1, spacer_in * inch),
        Paragraph("5. Eligibility and Repayment Conditions", H2),
        _p("(a) Applicants must be between 21 and 60 years of age at the time of application."),
        _gap(),
        _p("(b) Applicants must have a minimum credit score of 700 to qualify for a standard personal loan."),
        _gap(),
        _p("(c) Applicants must provide salary slips for the last 3 months and bank statements for the last 6 months."),
        _gap(),
        _p("(d) Repayment is made through equated monthly instalments (EMI) debited on the due date each month."),
        _gap(),
        _p("(e) The borrower must keep sufficient balance in the linked account at least 2 business days before the due date."),
        _gap(),
        _p("(f) Failure to repay 3 consecutive instalments classifies the account as delinquent."),
    ]
    path = out / "Acme_Loan_Policy_v3.pdf"
    _build(path, story)
    return path


def operations_notice(out: Path = OUT) -> Path:
    story = [
        Paragraph("Acme Operations Notice", H1),
        _p("Effective Date: 1 February 2025"),
        _p("Notice Reference: OPS-2025-014"),
        _gap(0.15),
        Paragraph("1. Late Payment Update", H2),
        _p("Effective immediately, a late payment fee of 5% per month applies after the due date for all delinquent personal loan accounts."),
        _gap(),
        _p("The grace period for all delinquent accounts is 5 days after the due date."),
        PageBreak(),
        Paragraph("2. Early Closure", H2),
        _p("Early closure is allowed after 3 months with no additional documentation."),
        Paragraph("3. Collections Desk", H2),
        _p("Customers can contact the collections desk between 9 AM and 6 PM on working days."),
        Paragraph("4. Reminder Schedule", H2),
        _p("Payment reminders are sent by SMS 3 days before the due date."),
    ]
    path = out / "Acme_Operations_Notice.pdf"
    _build(path, story)
    return path


def generate_all(out: Path = OUT) -> list[Path]:
    out.mkdir(parents=True, exist_ok=True)
    return [policy_v1(out), policy_v2(out), policy_v3(out), operations_notice(out)]


if __name__ == "__main__":
    for p in generate_all():
        print("wrote", p)
    print(f"Generated sample PDFs in {OUT}")
