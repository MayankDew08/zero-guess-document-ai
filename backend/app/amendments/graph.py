from __future__ import annotations

import re
import uuid
from datetime import datetime

import networkx as nx

from app.models.schemas import AmendmentChain, AmendmentEdge, Chunk

_AMEND_PATTERNS = [
    re.compile(r"\b(amends?|supersedes?|replaces?|overrides?)\b", re.IGNORECASE),
]
_EFFECTIVE_RE = re.compile(
    r"(?:effective|w\.e\.f\.?|with effect from)\s*[:\-]?\s*"
    r"(\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\d{4}[/-]\d{1,2}[/-]\d{1,2}|"
    r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?\s+\d{1,2},?\s+\d{4}|"
    r"\d{1,2}\s+(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?\s+\d{4})",
    re.IGNORECASE,
)
_DOC_REF_RE = re.compile(r"\b([A-Za-z][A-Za-z0-9_]*(?:[\s_-]+(?:v\d+|\d{4}|version\s*\d+|agreement|policy|amendment|addendum))[A-Za-z0-9_\s-]*)", re.IGNORECASE)


def extract_amendment_edges(chunks: list[Chunk], doc_name_by_id: dict[str, str]) -> list[AmendmentEdge]:
    edges: list[AmendmentEdge] = []
    seen: set[tuple[str, str, str]] = set()
    for chunk in chunks:
        text = chunk.text
        if not any(p.search(text) for p in _AMEND_PATTERNS):
            continue
        relation = _relation(text)
        effective_date = _extract_date(text)
        refs = _extract_doc_refs(text)
        from_doc_id = chunk.doc_id
        from_doc_name = chunk.doc_name
        # Heuristic: if the chunk references another known doc name/id, create edge from that doc to current doc.
        for ref in refs:
            to_doc_id = _match_doc(ref, doc_name_by_id)
            if not to_doc_id or to_doc_id == from_doc_id:
                continue
            key = (to_doc_id, from_doc_id, relation)
            if key in seen:
                continue
            seen.add(key)
            sentence_id = chunk.sentences[0].sentence_id if chunk.sentences else None
            edges.append(
                AmendmentEdge(
                    edge_id=f"ame_{uuid.uuid4().hex[:8]}",
                    from_doc_id=to_doc_id,
                    from_doc_name=doc_name_by_id.get(to_doc_id, to_doc_id),
                    to_doc_id=from_doc_id,
                    to_doc_name=from_doc_name,
                    relation=relation,
                    effective_date=effective_date,
                    change_subject=_guess_subject(chunk.text),
                    old_value=None,
                    new_value=None,
                    evidence_chunk_id=chunk.chunk_id,
                    evidence_sentence_id=sentence_id,
                    evidence_page=chunk.page,
                    evidence_quote=chunk.sentences[0].text if chunk.sentences else chunk.text[:300],
                    confidence=0.8,
                )
            )
    return edges


def build_amendment_chains(edges: list[AmendmentEdge], doc_name_by_id: dict[str, str]) -> list[AmendmentChain]:
    if not edges:
        return []
    g = nx.DiGraph()
    for e in edges:
        g.add_node(e.from_doc_id, name=doc_name_by_id.get(e.from_doc_id, e.from_doc_name))
        g.add_node(e.to_doc_id, name=doc_name_by_id.get(e.to_doc_id, e.to_doc_name))
        g.add_edge(e.from_doc_id, e.to_doc_id, edge=e)

    chains: list[AmendmentChain] = []
    # Build chains from weakly connected components that are DAG-like.
    for component in nx.weakly_connected_components(g):
        sub = g.subgraph(component).copy()
        comp_edges = [sub.edges[u, v]["edge"] for u, v in sub.edges]
        if not comp_edges:
            continue
        # Determine ordering by effective date then topological if possible.
        ordered = _order_nodes(sub, comp_edges)
        status = "resolved"
        if not nx.is_directed_acyclic_graph(sub):
            status = "ambiguous"
        active = ordered[-1] if ordered else None
        subject = _common_subject(comp_edges) or "amended rule"
        active_rule = None
        for e in reversed(comp_edges):
            if e.new_value:
                active_rule = e.new_value
                break
        chains.append(
            AmendmentChain(
                chain_id=f"chn_{uuid.uuid4().hex[:8]}",
                subject=subject,
                doc_ids_ordered=ordered,
                edges=comp_edges,
                active_doc_id=active,
                active_doc_name=doc_name_by_id.get(active, active) if active else None,
                active_rule=active_rule,
                status=status,
            )
        )
    return chains


def is_explained_by_amendment(doc_a: str, doc_b: str, edges: list[AmendmentEdge]) -> AmendmentEdge | None:
    for e in edges:
        pair = {e.from_doc_id, e.to_doc_id}
        if {doc_a, doc_b} == pair:
            return e
    return None


def _relation(text: str) -> str:
    t = text.lower()
    if "supersede" in t:
        return "SUPERSEDES"
    if "replace" in t:
        return "REPLACES"
    return "AMENDS"


def _extract_date(text: str) -> str | None:
    m = _EFFECTIVE_RE.search(text)
    if not m:
        return None
    raw = m.group(1).strip().replace(",", "")
    fmts = ["%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d", "%Y/%m/%d", "%d/%m/%y", "%d-%m-%y",
            "%b %d %Y", "%B %d %Y", "%d %b %Y", "%d %B %Y"]
    for fmt in fmts:
        try:
            return datetime.strptime(raw, fmt).strftime("%Y-%m-%d")
        except Exception:
            pass
    return raw


def _extract_doc_refs(text: str) -> list[str]:
    refs = []
    for m in _DOC_REF_RE.finditer(text):
        refs.append(m.group(1).strip())
    # also catch simple patterns like "Version 1", "v2"
    for m in re.finditer(r"\b(v\d+|version\s*\d+)\b", text, re.IGNORECASE):
        refs.append(m.group(1).strip())
    return refs


def _match_doc(ref: str, doc_name_by_id: dict[str, str]) -> str | None:
    ref_norm = re.sub(r"[^a-z0-9]+", "", ref.lower())
    if not ref_norm:
        return None
    for doc_id, name in doc_name_by_id.items():
        name_norm = re.sub(r"[^a-z0-9]+", "", name.lower())
        id_norm = re.sub(r"[^a-z0-9]+", "", doc_id.lower())
        if ref_norm and (ref_norm in name_norm or ref_norm in id_norm or name_norm in ref_norm or id_norm in ref_norm):
            # avoid overly broad matches
            if len(ref_norm) >= 2:
                return doc_id
    return None


def _guess_subject(text: str) -> str | None:
    # crude heuristic for demo
    for kw in ["interest rate", "late fee", "penalty", "tenure", "eligibility", "coverage", "waiting period"]:
        if kw in text.lower():
            return kw
    return None


def _order_nodes(g: nx.DiGraph, edges: list[AmendmentEdge]) -> list[str]:
    # Try topological order; fall back to effective date order.
    try:
        if nx.is_directed_acyclic_graph(g):
            return list(nx.topological_sort(g))
    except Exception:
        pass
    # effective date ordering
    doc_dates: dict[str, str] = {}
    for e in edges:
        if e.effective_date:
            doc_dates.setdefault(e.to_doc_id, e.effective_date)
            doc_dates.setdefault(e.from_doc_id, doc_dates.get(e.from_doc_id, "9999-99-99"))
    nodes = list(g.nodes)
    nodes.sort(key=lambda n: doc_dates.get(n, "9999-99-99"))
    return nodes


def _common_subject(edges: list[AmendmentEdge]) -> str | None:
    subjects = [e.change_subject for e in edges if e.change_subject]
    if not subjects:
        return None
    # most common
    return max(set(subjects), key=subjects.count)
