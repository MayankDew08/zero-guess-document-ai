"""Pipeline stage telemetry + SSE route (all providers are fakes: no model downloads)."""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

import app.main as main
from app.core.config import settings
from app.models.schemas import StageEvent
from app.qa.llm import FakeLLMProvider
from app.qa.service import ask_question
from app.qa.stages import StageReporter
from app.retrieval.embeddings import FakeEmbeddingProvider
from app.retrieval.reranker import FakeRerankerProvider
from app.verification.nli import FakeNLIProvider
from tests.helpers import sample_store

LATE_Q = "What is the late payment fee according to the latest active rule?"
COMPOUND_Q = "What is the late payment fee and what is the grace period?"
CANON = ["retrieve", "rerank", "draft", "resolve", "verify", "lineage"]


@pytest.fixture(autouse=True)
def _threshold(monkeypatch):
    monkeypatch.setattr(settings, "rerank_abstain_threshold", 0.0)


def _run(question=LATE_Q, history=None, reranker=None, nli=None, on_stage=True):
    events: list[StageEvent] = []
    resp = ask_question(question=question, app_store=sample_store(), embedding_provider=FakeEmbeddingProvider(),
                        reranker_provider=reranker or FakeRerankerProvider(), nli_provider=nli or FakeNLIProvider(),
                        llm_provider=FakeLLMProvider(), history=history, on_stage=events.append if on_stage else None)
    return resp, events


_RANDOM = {"request_id", "contradiction_id", "chain_id", "edge_id", "created_at"}


def _stable(o):
    """Drop per-run random ids/timestamps (they differ between any two identical runs)."""
    if isinstance(o, dict):
        return {k: _stable(v) for k, v in o.items() if k not in _RANDOM}
    if isinstance(o, list):
        return [_stable(v) for v in o]
    return o


def _first_seen(events):
    order: list[str] = []
    for e in events:
        if e.stage not in order:
            order.append(e.stage)
    return order


def _final(events):
    return {e.stage: e for e in events}  # later events overwrite earlier ones, exactly like the UI


def test_stages_in_pipeline_order_and_all_done():
    _, events = _run()
    assert _first_seen(events) == CANON
    final = _final(events)
    assert all(final[s].status == "done" for s in CANON)
    assert final["retrieve"].detail["candidates"] > 0
    assert final["rerank"].detail["passed"] is True and final["rerank"].detail["kept"] > 0
    assert final["draft"].detail["claims"] >= 1
    assert final["lineage"].detail["conflicts"] >= 0
    assert all(final[s].ms is not None for s in CANON)


def test_crag_abstain_skips_generation_stages(monkeypatch):
    monkeypatch.setattr(settings, "rerank_abstain_threshold", 99.0)
    resp, events = _run()
    assert resp.status == "abstained"
    final = _final(events)
    assert final["retrieve"].status == "done" and final["rerank"].status == "done"
    assert final["rerank"].detail["passed"] is False
    for s in ("draft", "resolve", "verify"):
        assert final[s].status == "skipped", s


def test_on_stage_does_not_change_the_answer():
    a, _ = _run(on_stage=False)
    b, events = _run(on_stage=True)
    assert events
    assert _stable(a.model_dump()) == _stable(b.model_dump())


def test_compound_question_reports_each_stage_once():
    from app.qa.decompose import split_question_parts
    assert len(split_question_parts(COMPOUND_Q)) >= 2, "test premise: question must split into parts"
    _, events = _run(COMPOUND_Q)
    for stage in CANON:
        mine = [e for e in events if e.stage == stage]
        assert sum(e.status == "start" for e in mine) <= 1, f"{stage} replayed"
        # never a 'start' after the stage finished
        seen_done = False
        for e in mine:
            assert not (seen_done and e.status == "start"), f"{stage} went backwards"
            seen_done = seen_done or e.status == "done"
    assert _final(events)["retrieve"].detail["parts"] >= 2


def test_followup_adds_understand_stage_only_with_history():
    from app.models.schemas import ChatTurn
    _, no_hist = _run()
    assert "understand" not in _first_seen(no_hist)
    hist = [ChatTurn(role="user", question=LATE_Q, answer_summary="2% per month", pending_calculation=None)]
    _, with_hist = _run("What about in v1?", history=hist)
    assert _first_seen(with_hist)[0] == "understand"


class _LazyReranker(FakeRerankerProvider):
    model_name = "fake-reranker"

    def __init__(self):
        self.loaded = False

    def is_loaded(self):
        return self.loaded

    def rerank(self, query, texts):
        self.loaded = True
        return super().rerank(query, texts)


class _LazyNLI(FakeNLIProvider):
    model_name = "fake-nli"

    def __init__(self):
        self.loaded = False

    def is_loaded(self):
        return self.loaded

    def predict(self, *a, **k):
        self.loaded = True
        return super().predict(*a, **k)


def test_model_loading_is_announced_before_the_blocking_call_and_cleared_after():
    _, events = _run(reranker=_LazyReranker(), nli=_LazyNLI())
    rr = [e for e in events if e.stage == "rerank"]
    vf = [e for e in events if e.stage == "verify"]
    assert rr[0].status == "start" and rr[0].detail.get("loading_model") == "fake-reranker"
    assert vf[0].status == "start" and vf[0].detail.get("loading_model") == "fake-nli"
    assert "loading_model" not in rr[-1].detail and "loading_model" not in vf[-1].detail


def test_warm_models_never_report_loading():
    r, n = _LazyReranker(), _LazyNLI()
    r.loaded = n.loaded = True
    _, events = _run(reranker=r, nli=n)
    assert not any("loading_model" in e.detail for e in events)


def test_reporter_never_replays_and_skips_unrun_stages():
    out: list[StageEvent] = []
    rep = StageReporter(out.append)
    rep.start("retrieve")
    rep.start("rerank")
    rep.done("retrieve", candidates=3)
    rep.start("retrieve")  # finished stage: ignored
    rep.done("rerank")
    rep.finalize()
    assert [e.status for e in out if e.stage == "retrieve"] == ["start", "done", "done"]
    assert {e.stage: e.status for e in out}["draft"] == "skipped"
    assert "repair" not in {e.stage for e in out}  # optional stages only appear when they run
    StageReporter(None).start("x")  # disabled reporter is a no-op


# ------------------------------------------------------------------ SSE route
@pytest.fixture
def api(monkeypatch):
    monkeypatch.setattr(main, "store", sample_store())

    def fake_providers(**kw):
        return ask_question(**kw, embedding_provider=FakeEmbeddingProvider(), reranker_provider=FakeRerankerProvider(),
                            nli_provider=FakeNLIProvider(), llm_provider=FakeLLMProvider())
    monkeypatch.setattr(main, "ask_question", fake_providers)
    return TestClient(main.app)  # no context manager: lifespan would load real models


def _parse_sse(text: str):
    out = []
    for block in text.split("\n\n"):
        lines = [ln for ln in block.splitlines() if not ln.startswith(":")]
        if not lines:
            continue
        ev = next(ln[7:] for ln in lines if ln.startswith("event: "))
        data = json.loads(next(ln[6:] for ln in lines if ln.startswith("data: ")))
        out.append((ev, data))
    return out


def test_stream_route_emits_stages_then_the_same_payload_as_ask(api):
    with api.stream("POST", "/api/ask/stream", json={"question": LATE_Q}) as r:
        assert r.status_code == 200 and r.headers["content-type"].startswith("text/event-stream")
        events = _parse_sse("".join(r.iter_text()))
    kinds = [k for k, _ in events]
    assert kinds[-1] == "result" and kinds.count("result") == 1 and set(kinds[:-1]) == {"stage"}
    assert [d["stage"] for k, d in events if k == "stage"][0] == "retrieve"
    result = events[-1][1]
    plain = api.post("/api/ask", json={"question": LATE_Q}).json()
    assert _stable(result) == _stable(plain)
    assert "explanation" in result and "pipeline_trace" in result


def test_stream_route_validates_before_streaming(api):
    assert api.post("/api/ask/stream", json={"question": "  "}).status_code == 400
    assert api.post("/api/ask/stream", json={"question": "hi", "workspace": "nope"}).status_code == 400


def test_stream_route_reports_pipeline_errors_as_error_event(api, monkeypatch):
    def boom(**_kw):
        raise RuntimeError("llm exploded")
    monkeypatch.setattr(main, "ask_question", boom)
    with api.stream("POST", "/api/ask/stream", json={"question": LATE_Q}) as r:
        events = _parse_sse("".join(r.iter_text()))
    assert events == [("error", {"detail": "llm exploded"})]
