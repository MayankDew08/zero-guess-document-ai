"""Executive, print-ready HTML audit report for one /api/ask response."""
from __future__ import annotations

import os
from html import escape as e

from app.core.config import settings
from app.models.schemas import AskResponse

_CSS = """
:root{--ink:#0f172a;--mut:#64748b;--line:#e2e8f0;--ok:#047857;--bad:#b91c1c;--warn:#b45309;--bg:#f8fafc}
*{box-sizing:border-box}body{font:14px/1.5 -apple-system,Segoe UI,Roboto,Arial,sans-serif;color:var(--ink);margin:0;background:#fff}
.wrap{max-width:1040px;margin:0 auto;padding:28px}h1{font-size:22px;margin:0}h2{font-size:15px;margin:26px 0 8px;padding-bottom:4px;border-bottom:2px solid var(--ink);text-transform:uppercase;letter-spacing:.04em}
.meta{display:grid;grid-template-columns:repeat(2,1fr);gap:4px 24px;background:var(--bg);border:1px solid var(--line);border-radius:8px;padding:12px;margin-top:12px;font-size:12.5px}
.meta b{color:var(--mut);font-weight:600}.badge{display:inline-block;padding:2px 9px;border-radius:999px;font-size:12px;font-weight:600;border:1px solid}
.b-ok{color:var(--ok);border-color:var(--ok);background:#ecfdf5}.b-bad{color:var(--bad);border-color:var(--bad);background:#fef2f2}.b-warn{color:var(--warn);border-color:var(--warn);background:#fffbeb}.b-mut{color:var(--mut);border-color:var(--mut)}
.metrics{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin-top:14px}.metric{border:1px solid var(--line);border-radius:8px;padding:10px;text-align:center}
.metric .v{font-size:22px;font-weight:700}.metric .l{font-size:11px;color:var(--mut);text-transform:uppercase}
table{width:100%;border-collapse:collapse;font-size:13px}th,td{border:1px solid var(--line);padding:7px 9px;vertical-align:top;text-align:left}th{background:var(--bg);font-size:12px}
blockquote{margin:4px 0 0;padding:6px 10px;border-left:4px solid #f59e0b;background:#fffbeb;font-size:12.5px}
.card{border:1px solid var(--line);border-radius:8px;padding:10px 12px;margin:8px 0;page-break-inside:avoid}.src{color:var(--mut);font-size:12px}
code{background:#f1f5f9;padding:1px 5px;border-radius:4px;font-size:12px}.none{color:var(--ok)}.foot{margin-top:28px;color:var(--mut);font-size:11.5px;border-top:1px solid var(--line);padding-top:8px}
@media print{.wrap{padding:0}h2{break-after:avoid}}
"""


def _badge(status: str) -> str:
    cls = {"answered": "b-ok", "supported": "b-ok", "partially_answered": "b-warn", "contradicted": "b-bad",
           "abstained": "b-mut", "blocked": "b-bad", "confirmed": "b-bad"}.get(status, "b-mut")
    return f'<span class="badge {cls}">{e(status)}</span>'


def _pct(v) -> str:
    return "N/A" if v is None else f"{v}%"


def _quote(text: str) -> str:
    return f"<blockquote>“{e(text)}”</blockquote>"


def render_html(resp: AskResponse) -> str:
    offline = os.environ.get("HF_HUB_OFFLINE", "").strip() in {"1", "true", "TRUE"}
    bd = resp.confidence_breakdown or {}
    out: list[str] = []
    out.append(f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Audit Report {e(resp.request_id)}</title><style>{_CSS}</style></head><body><div class="wrap">
<h1>Zero-Guessing Document AI — Verification Audit Report</h1>
<div class="meta">
<div><b>Request ID</b> <code>{e(resp.request_id)}</code></div><div><b>Generated</b> {e(resp.created_at or "n/a")}</div>
<div><b>Status</b> {_badge(resp.status)}</div><div><b>Mode</b> {'<span class="badge b-ok">OFFLINE · local models only · zero paid APIs</span>' if offline else '<span class="badge b-warn">online model hub allowed</span>'}</div>
<div><b>Generator</b> {e(settings.ollama_model)} (Ollama)</div><div><b>Embeddings</b> {e(settings.embedding_model)}</div>
<div><b>Reranker</b> {e(settings.reranker_model)}</div><div><b>NLI</b> {e(settings.nli_model)}</div>
</div>
<h2>Question</h2><p>{e(resp.question)}</p>
<h2>Answer</h2><p>{e(resp.answer)}</p>
<div class="metrics">
<div class="metric"><div class="v">{_pct(resp.faithfulness_pct)}</div><div class="l">Faithfulness ({resp.verified_sentences_count}/{resp.total_shown_sentences} shown claims verified)</div></div>
<div class="metric"><div class="v">{_pct(resp.draft_support_pct)}</div><div class="l">Draft support ({resp.drafted_claims_count} drafted)</div></div>
<div class="metric"><div class="v">{resp.blocked_claims_count}</div><div class="l">Blocked claims</div></div>
<div class="metric"><div class="v">{'N/A' if resp.confidence is None else f'{resp.confidence * 100:.1f}%'}</div><div class="l">Confidence · retrieval {bd.get('retrieval', 0):.2f} · verification {bd.get('verification', 0):.2f} · conflict penalty {bd.get('contradiction_penalty', 0):.2f}</div></div>
</div>""")

    out.append("<h2>Verified Claims</h2>")
    if not resp.claims:
        out.append('<p class="src">No claim survived verification (see Missing Evidence).</p>')
    for i, c in enumerate(resp.claims, 1):
        out.append(f'<div class="card"><b>{i}. {e(c.text)}</b> {_badge(c.status)}')
        nv = c.numeric_verification or {}
        for cit in c.citations:
            sc = cit.nli_scores or {}
            out.append(f'<div class="src">{e(cit.doc_name)} · page {cit.page} · <code>{e(cit.sentence_id)}</code> · '
                       f'NLI: {e(cit.nli_label or "n/a")} (entailment {sc.get("entailment", 0):.2f}) · '
                       f'numeric/date check: {"PASS" if nv.get("ok", True) else "FAIL"}</div>{_quote(cit.quote)}')
        out.append("</div>")

    out.append("<h2>Blocked / Rejected Claims</h2>")
    if not resp.blocked_claims:
        out.append('<p class="none">None — all drafted claims passed deterministic verification.</p>')
    for c in resp.blocked_claims:
        out.append(f'<div class="card"><b>{e(c.text)}</b> {_badge("blocked")}<div class="src">Reason: {e(c.reason or "n/a")}</div>')
        for cit in c.citations:
            out.append(f'<div class="src">cited {e(cit.doc_name)} p.{cit.page} <code>{e(cit.sentence_id)}</code></div>{_quote(cit.quote)}')
        out.append("</div>")
    if resp.missing_evidence:
        out.append("<h2>Missing Evidence</h2><ul>" + "".join(f"<li>{e(m)}</li>" for m in resp.missing_evidence) + "</ul>")

    out.append("<h2>Contradiction Alerts (unresolved, not explained by amendments)</h2>")
    if not resp.contradictions:
        out.append('<p class="none">No unresolved contradictions for the subjects asked about.</p>')
    else:
        out.append("<table><tr><th>Subject</th><th>Explanation</th><th>NLI</th><th>Quote A</th><th>Quote B</th></tr>")
        for c in resp.contradictions:
            vals = (c.values + [None, None])[:2]
            cells = "".join(
                f'<td><b>{e(v.doc_name)}</b> · p.{v.page}<br><code>{e(v.sentence_id or "")}</code>{_quote(v.quote)}</td>' if v else "<td>—</td>"
                for v in vals)
            nli = "n/a" if c.nli_contradiction_score is None else f"{c.nli_contradiction_score:.2f}"
            out.append(f"<tr><td><b>{e(c.subject)}</b><br>{_badge(c.status)}</td><td>{e(c.explanation)}</td><td>{nli}</td>{cells}</tr>")
        out.append("</table>")

    out.append("<h2>Amendment Chains</h2>")
    if not resp.amendment_chains:
        out.append('<p class="src">No amendment chain involves the retrieved documents.</p>')
    for ch in resp.amendment_chains:
        names = ch.doc_names_ordered or ch.doc_ids_ordered
        out.append(f'<div class="card"><b>Timeline (oldest → newest):</b> {" → ".join(e(n) for n in names)}<br>'
                   f'<b>Active document:</b> {e(ch.active_doc_name or "unknown")} {_badge(ch.status)}')
        out.append("<table><tr><th>Newer document</th><th>Relation</th><th>Older document</th><th>Effective</th><th>Clause (verbatim)</th></tr>")
        for ed in ch.edges:
            out.append(f"<tr><td>{e(ed.from_doc_name)}</td><td><b>{e(ed.relation)}</b></td><td>{e(ed.to_doc_name)}</td>"
                       f"<td>{e(ed.effective_date or '—')}</td><td>{e(ed.from_doc_name)} · p.{ed.evidence_page}{_quote(ed.evidence_quote)}</td></tr>")
        out.append("</table></div>")

    if resp.calculation:
        k = resp.calculation
        out.append(f"<h2>Calculation Working</h2><div class='card'><b>Formula:</b> <code>{e(k.formula)}</code><table><tr><th>Input</th><th>Value</th></tr>"
                   + "".join(f"<tr><td>{e(str(a))}</td><td>{e(str(b))}</td></tr>" for a, b in k.inputs.items())
                   + "</table><ol>" + "".join(f"<li>{e(s)}</li>" for s in k.steps) + f"</ol><p><b>Result: {e(k.result)}</b> (deterministic Decimal arithmetic; no LLM math)</p>")
        if k.citation:
            out.append(f'<div class="src">Rate source: {e(k.citation.doc_name)} p.{k.citation.page} <code>{e(k.citation.sentence_id)}</code></div>{_quote(k.citation.quote)}')
        out += [f'<p class="src">⚠ {e(w)}</p>' for w in k.warnings]
        out.append("</div>")

    t = resp.pipeline_trace
    out.append("<h2>Verification Pipeline Trace</h2>")
    if t:
        g1, g2, g3, g4 = t.gate1_retrieval, t.gate2_citation_resolution, t.gate3_nli_and_numeric, t.gate4_lineage_and_conflicts
        mr = "n/a" if g1.max_rerank_score is None else f"{g1.max_rerank_score:.3f}"
        out.append(f"""<table><tr><th>Gate</th><th>Signals</th><th>Result</th></tr>
<tr><td>1 · CRAG retrieval</td><td>{g1.hybrid_candidates} hybrid candidates → {g1.reranked_kept} kept · max rerank {mr} vs threshold {g1.threshold}</td><td>{_badge('answered' if g1.passed else 'abstained')} {'PASS' if g1.passed else 'ABSTAIN'}</td></tr>
<tr><td>2 · Citation resolution</td><td>{g2.drafted_claims} drafted · {g2.resolved_citations} resolved to stored sentences · {g2.rejected_invalid_ids} invalid ids rejected</td><td>{_badge('answered' if not g2.rejected_invalid_ids else 'partially_answered')}</td></tr>
<tr><td>3 · NLI + numeric/date</td><td>NLI {g3.nli_passed} pass / {g3.nli_failed} fail · numeric {g3.numeric_passed} pass / {g3.numeric_failed} fail</td><td>{_badge('answered' if not (g3.nli_failed or g3.numeric_failed) else 'partially_answered')}</td></tr>
<tr><td>4 · Lineage &amp; abstention</td><td>{g4.amendment_chains_found} amendment chain(s) · {g4.superseded_docs_filtered} superseded doc(s) excluded from conflicts · {g4.unresolved_contradictions} unresolved contradiction(s)</td><td>{_badge('abstained' if g4.abstained else 'answered')}</td></tr></table>""")
    else:
        out.append('<p class="src">No trace recorded.</p>')
    out.append('<div class="foot">Every quote above is resolved by the backend from stored document sentences — the LLM never types a quote. '
               'Claims failing citation resolution, NLI entailment or numeric/date matching are blocked, not shown.</div></div></body></html>')
    return "".join(out)
