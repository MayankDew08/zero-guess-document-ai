from __future__ import annotations

from pathlib import Path

from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle, PageBreak
from reportlab.lib import colors

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "samples"
OUT.mkdir(parents=True, exist_ok=True)

styles = getSampleStyleSheet()
H1 = styles["Heading1"]
H2 = styles["Heading2"]
N = styles["Normal"]


def doc(path: Path, story):
    d = SimpleDocTemplate(str(path), pagesize=LETTER, leftMargin=0.75 * inch, rightMargin=0.75 * inch)
    d.build(story)


def policy_v1():
    story = [
        Paragraph("Acme Loan Policy - Version 1", H1),
        Paragraph("Effective Date: 2024-01-01", N),
        Spacer(1, 0.2 * inch),
        Paragraph("1. Interest Rate", H2),
        Paragraph("The interest rate is 5% per year for all standard personal loans.", N),
        Spacer(1, 0.1 * inch),
        Paragraph("2. Late Payment Fee", H2),
        Paragraph("A late payment fee of 1% per month applies after the due date.", N),
        Spacer(1, 0.1 * inch),
        Paragraph("3. Prepayment Penalty", H2),
        Paragraph("No prepayment penalty applies to standard personal loans.", N),
        Spacer(1, 0.1 * inch),
        Paragraph("4. Tenure", H2),
        Paragraph("The standard loan tenure is 12 months.", N),
    ]
    doc(OUT / "Acme_Loan_Policy_v1.pdf", story)


def policy_v2():
    story = [
        Paragraph("Acme Loan Policy - Version 2", H1),
        Paragraph("Effective Date: 2024-07-01", N),
        Spacer(1, 0.2 * inch),
        Paragraph("1. Interest Rate", H2),
        Paragraph("The interest rate is 6% per year for all standard personal loans. This amends Acme Loan Policy v1.", N),
        Spacer(1, 0.1 * inch),
        Paragraph("2. Late Payment Fee", H2),
        Paragraph("A late payment fee of 2% per month applies after the due date. This replaces the late fee in Acme Loan Policy v1.", N),
        Spacer(1, 0.1 * inch),
        Paragraph("3. Prepayment Penalty", H2),
        Paragraph("A prepayment penalty of 1% applies if the loan is closed within 6 months.", N),
        Spacer(1, 0.1 * inch),
        Paragraph("4. Tenure", H2),
        Paragraph("The standard loan tenure is 24 months. This supersedes Acme Loan Policy v1.", N),
    ]
    doc(OUT / "Acme_Loan_Policy_v2.pdf", story)


def policy_v3():
    story = [
        Paragraph("Acme Loan Policy - Version 3", H1),
        Paragraph("Effective Date: 2025-01-01", N),
        Spacer(1, 0.2 * inch),
        Paragraph("1. Interest Rate", H2),
        Paragraph("The interest rate is 7% per year for all standard personal loans. This supersedes Acme Loan Policy v2.", N),
        Spacer(1, 0.1 * inch),
        Paragraph("2. Late Payment Fee", H2),
        Paragraph("A late payment fee of 2% per month applies after the due date.", N),
        Spacer(1, 0.1 * inch),
        Paragraph("3. Eligibility", H2),
        Paragraph("Applicants must have a minimum credit score of 700 to qualify for a standard personal loan.", N),
        Spacer(1, 0.1 * inch),
        Paragraph("4. Fee Schedule Table", H2),
    ]
    data = [
        ["Fee Type", "Amount", "When Applied"],
        ["Processing Fee", "INR 500", "At disbursement"],
        ["Late Payment Fee", "2% per month", "After due date"],
        ["Prepayment Penalty", "1%", "Within 6 months"],
    ]
    t = Table(data, colWidths=[2.2 * inch, 1.8 * inch, 2.2 * inch])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("PADDING", (0, 0), (-1, -1), 6),
    ]))
    story.append(t)
    doc(OUT / "Acme_Loan_Policy_v3.pdf", story)


def contradictory_notice():
    story = [
        Paragraph("Acme Operations Notice", H1),
        Paragraph("Effective Date: 2025-02-01", N),
        Spacer(1, 0.2 * inch),
        Paragraph("Late Payment Update", H2),
        Paragraph("A late payment fee of 5% per month applies after the due date for all delinquent accounts.", N),
        Spacer(1, 0.1 * inch),
        Paragraph("Early Closure", H2),
        Paragraph("Early closure is allowed after 3 months with no additional documentation.", N),
    ]
    doc(OUT / "Acme_Operations_Notice.pdf", story)


if __name__ == "__main__":
    policy_v1()
    policy_v2()
    policy_v3()
    contradictory_notice()
    print(f"Generated sample PDFs in {OUT}")
