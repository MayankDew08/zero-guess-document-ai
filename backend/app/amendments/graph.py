"""Amendment graph.

Edge semantics: ``newer_doc --[SUPERSEDES | AMENDS | REPLACES]--> older_doc``.
So v3 SUPERSEDES v2 and v2 SUPERSEDES v1; the chronological chain is v1 -> v2 -> v3 and the
active document is the one with no incoming edge (nothing supersedes it).
"""
from __future__ import annotations

import re
import uuid
from datetime import datetime
from pathlib import Path

import networkx as nx

from app.models.schemas import AmendmentChain, AmendmentEdge, Chunk

_AMEND_RE = re.compile(
    r"\b(amends?|amended|supersedes?|superseded|replaces?|replaced|overrides?|overridden)\b"
    r"|\bin\s+partial\s+modification\s+of\b|\bhereby\s+(?:modified|amended)\b|\bamended\s+to\s+read\b",
    re.IGNORECASE,
)
# Indian regulatory references: "Circular No. DOR.STR.REC.45/2023-24", "Master Direction - Credit Cards"
_CIRCULAR_RE = re.compile(r"circular\s+no\.?\s*:?\s*([A-Za-z0-9][A-Za-z0-9./_\-]*[A-Za-z0-9])", re.IGNORECASE)
_MASTER_DIR_RE = re.compile(r"master\s+(?:direction|circular)\b[^,.;()\n]*?(?=\s+dated\b|\s+w\.e\.f|,|;|\(|\.\s|\.$|$)", re.IGNORECASE)
_PASSIVE_RE = re.compile(r"\b(?:superseded|replaced|amended|overridden)\s+by\b", re.IGNORECASE)
_EFFECTIVE_RE = re.compile(
    r"(?:effective(?:\s+date)?|w\.e\.f\.?|with\s+effect\s+from|dated)\s*[:\-]?\s*"
    r"(\d{1,2}[/.-]\d{1,2}[/.-]\d{2,4}|\d{4}[/-]\d{1,2}[/-]\d{1,2}|"
    r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?\s+\d{1,2},?\s+\d{4}|"
    r"\d{1,2}\s+(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?\s+\d{4})",
    re.IGNORECASE,
)
_VERSION_REF_RE = re.compile(r"\b(?:v|version)\s*(\d+)\b", re.IGNORECASE)
_SUBJECT_WORDS = ["interest rate", "late fee", "late payment", "penalty", "tenure", "eligibility", "grace period",
                  "coverage", "waiting period"]


# ------------------------------------------------------------------------------------------
# extraction
# ------------------------------------------------------------------------------------------
def extract_amendment_edges(chunks: list[Chunk], doc_name_by_id: dict[str, str]) -> list[AmendmentEdge]:
    """One edge per amendment *sentence* (never a title/heading) that references another known document."""
    edges: list[AmendmentEdge] = []
    seen: set[tuple[str, str, str]] = set()
    doc_dates = _doc_effective_dates(chunks)
    doc_ids = _doc_identifiers(chunks)
    for chunk in chunks:
        if chunk.chunk_type == "table":
            continue
        for sent in chunk.sentences:
            if not _AMEND_RE.search(sent.text):
                continue
            targets = _referenced_docs(sent.text, chunk.doc_id, doc_name_by_id, doc_ids)
            if not targets:
                continue
            relation = _relation(sent.text)
            passive = bool(_PASSIVE_RE.search(sent.text))
            for ref_id in targets:
                # Active voice: this (newer) doc acts on the referenced (older) doc.
                # Passive ("v1 is superseded by v2"): the referenced doc is the newer one.
                newer, older = (ref_id, chunk.doc_id) if passive else (chunk.doc_id, ref_id)
                key = (newer, older, relation)
                if key in seen:
                    continue
                seen.add(key)
                edges.append(AmendmentEdge(
                    edge_id=f"ame_{uuid.uuid4().hex[:8]}",
                    from_doc_id=newer,
                    from_doc_name=doc_name_by_id.get(newer, newer),
                    to_doc_id=older,
                    to_doc_name=doc_name_by_id.get(older, older),
                    relation=relation,
                    effective_date=_extract_date(sent.text) or doc_dates.get(newer),
                    change_subject=_guess_subject(sent.text),
                    evidence_chunk_id=chunk.chunk_id,
                    evidence_sentence_id=sent.sentence_id,
                    evidence_page=chunk.page,
                    evidence_quote=sent.text,
                    confidence=0.9,
                ))
    return edges


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", re.sub(r"version", "v", s.lower()))


def _family_version(name: str) -> tuple[str, int | None]:
    stem = Path(name).stem
    m = re.search(r"[\s_\-]*v(?:ersion)?[\s_\-]*(\d+)\s*$", stem, re.IGNORECASE)
    if not m:
        return _norm(stem), None
    return _norm(stem[: m.start()]), int(m.group(1))


def _doc_identifiers(chunks: list[Chunk]) -> dict[str, set[str]]:
    """Normalised circular numbers / Master Direction titles a document declares in its header
    (first 4 sentences), so other documents can reference it by that identifier."""
    out: dict[str, set[str]] = {}
    seen: dict[str, int] = {}
    for c in chunks:
        for s in c.sentences:
            n = seen.get(c.doc_id, 0)
            if n >= 4 or c.page != 1:
                continue
            seen[c.doc_id] = n + 1
            ids = out.setdefault(c.doc_id, set())
            ids.update(_norm(m.group(1)) for m in _CIRCULAR_RE.finditer(s.text))
            ids.update(_norm(m.group(0)) for m in _MASTER_DIR_RE.finditer(s.text))
    return out


def _referenced_docs(sentence: str, own_id: str, doc_name_by_id: dict[str, str],
                     doc_ids: dict[str, set[str]] | None = None) -> list[str]:
    sent_n = _norm(sentence)
    found: list[str] = []
    refs = {_norm(m.group(1)) for m in _CIRCULAR_RE.finditer(sentence)} | {_norm(m.group(0)) for m in _MASTER_DIR_RE.finditer(sentence)}
    refs.discard("")
    for doc_id, ids in (doc_ids or {}).items():
        if doc_id != own_id and refs & ids:
            found.append(doc_id)
    for doc_id, name in doc_name_by_id.items():
        if doc_id != own_id and doc_id not in found:
            name_n = _norm(Path(name).stem)
            if any(len(r) > 6 and r in name_n for r in refs):
                found.append(doc_id)
    for doc_id, name in doc_name_by_id.items():
        if doc_id == own_id:
            continue
        stem_n = _norm(Path(name).stem)
        for m in re.finditer(re.escape(stem_n), sent_n):
            if not sent_n[m.end(): m.end() + 1].isdigit():
                if doc_id not in found:
                    found.append(doc_id)
                break
    if found:
        return found
    # bare "v2" / "version 2": resolve inside the current doc's family
    own_family, _ = _family_version(doc_name_by_id.get(own_id, own_id))
    for m in _VERSION_REF_RE.finditer(sentence):
        want = int(m.group(1))
        for doc_id, name in doc_name_by_id.items():
            fam, ver = _family_version(name)
            if doc_id != own_id and fam == own_family and ver == want and doc_id not in found:
                found.append(doc_id)
    return found


def _doc_effective_dates(chunks: list[Chunk]) -> dict[str, str]:
    out: dict[str, str] = {}
    for c in chunks:
        if c.doc_id in out:
            continue
        for s in c.sentences:
            if s.text.lower().startswith("effective date"):
                d = _extract_date(s.text)
                if d:
                    out[c.doc_id] = d
                    break
    return out


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
    for fmt in ["%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y", "%Y-%m-%d", "%Y/%m/%d", "%d/%m/%y", "%d-%m-%y",
                "%b %d %Y", "%B %d %Y", "%d %b %Y", "%d %B %Y"]:
        try:
            return datetime.strptime(raw, fmt).strftime("%Y-%m-%d")
        except ValueError:
            pass
    return raw


def _guess_subject(text: str) -> str | None:
    low = text.lower()
    return next((kw for kw in _SUBJECT_WORDS if kw in low), None)


# ------------------------------------------------------------------------------------------
# graph queries
# ------------------------------------------------------------------------------------------
def _graph(edges: list[AmendmentEdge]) -> nx.DiGraph:
    g = nx.DiGraph()
    for e in edges:
        g.add_edge(e.from_doc_id, e.to_doc_id, edge=e)
    return g


def is_amendment_pair(doc_a: str, doc_b: str, edges: list[AmendmentEdge]) -> bool:
    """True when one doc (transitively) supersedes/amends the other, e.g. v3 -> v2 -> v1 makes
    (v1, v3) an amendment pair even though they are two hops apart."""
    if not doc_a or not doc_b or doc_a == doc_b:
        return False
    g = _graph(edges)
    if doc_a not in g or doc_b not in g:
        return False
    return nx.has_path(g, doc_a, doc_b) or nx.has_path(g, doc_b, doc_a)


def superseded_doc_ids(edges: list[AmendmentEdge]) -> set[str]:
    """Docs that some newer doc supersedes/amends/replaces (they have an incoming edge)."""
    return {e.to_doc_id for e in edges}


def active_chain_doc_ids(edges: list[AmendmentEdge]) -> set[str]:
    """Heads of amendment chains: they act on an older doc but nothing acts on them."""
    return {e.from_doc_id for e in edges} - superseded_doc_ids(edges)


# ------------------------------------------------------------------------------------------
# chains
# ------------------------------------------------------------------------------------------
def build_amendment_chains(edges: list[AmendmentEdge], doc_name_by_id: dict[str, str]) -> list[AmendmentChain]:
    if not edges:
        return []
    g = _graph(edges)
    chains: list[AmendmentChain] = []
    for comp in nx.weakly_connected_components(g):
        sub = g.subgraph(comp)
        sub_edges = [d["edge"] for _, _, d in sub.edges(data=True)]
        actives = [n for n in comp if sub.in_degree(n) == 0]
        active = _pick_active(actives, sub_edges)
        ordered = _order_nodes(sub, sub_edges)
        chains.append(AmendmentChain(
            chain_id=f"chain_{uuid.uuid4().hex[:8]}",
            subject=_common_subject(sub_edges) or "policy versions",
            doc_ids_ordered=ordered,
            doc_names_ordered=[doc_name_by_id.get(n, n) for n in ordered],
            edges=sub_edges,
            active_doc_id=active,
            active_doc_name=doc_name_by_id.get(active, active) if active else None,
            active_rule=None,
            status="resolved" if len(actives) == 1 else "ambiguous",
        ))
    return chains


def _pick_active(candidates: list[str], edges: list[AmendmentEdge]) -> str | None:
    if not candidates:
        return None

    def score(doc_id: str):
        dates = [e.effective_date for e in edges if e.from_doc_id == doc_id and e.effective_date]
        m = re.search(r"v(?:ersion)?\s*(\d+)", doc_id, re.IGNORECASE)
        return (max(dates) if dates else "", int(m.group(1)) if m else -1, doc_id)

    return max(candidates, key=score)


def _order_nodes(g: nx.DiGraph, edges: list[AmendmentEdge]) -> list[str]:
    """Chronological, oldest -> newest (edges point newer -> older, so reverse topological order)."""
    if nx.is_directed_acyclic_graph(g):
        return list(reversed(list(nx.topological_sort(g))))
    return sorted(g.nodes)


def _common_subject(edges: list[AmendmentEdge]) -> str | None:
    subjects = [e.change_subject for e in edges if e.change_subject]
    return max(set(subjects), key=subjects.count) if subjects else None
