"""Pipeline stage telemetry for the UI. Pure observation: nothing here influences retrieval, drafting or verification.

Each stage is reported at most once per request (later events for a stage key update it in place), so compound
questions, repair rounds etc. never replay earlier stages. Optional stages (`understand`, `repair`, `translate`) only
appear when they actually run; canonical stages that never ran are reported as `skipped` by `finalize()`.
"""
from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

from app.models.schemas import StageEvent

CANONICAL = ["retrieve", "rerank", "draft", "resolve", "verify", "lineage"]


class StageReporter:
    def __init__(self, sink: Callable[[StageEvent], None] | None = None):
        self._sink = sink
        self._t0: dict[str, float] = {}
        self._state: dict[str, str] = {}
        self._detail: dict[str, dict[str, Any]] = {}
        self._ms: dict[str, int] = {}
        self._active: str | None = None

    @property
    def enabled(self) -> bool:
        return self._sink is not None

    def started(self, stage: str) -> bool:
        return stage in self._state

    def _emit(self, stage: str) -> None:
        if self._sink is None:
            return
        try:
            self._sink(StageEvent(stage=stage, status=self._state[stage], detail=dict(self._detail.get(stage, {})),  # type: ignore[arg-type]
                                  ms=self._ms.get(stage)))
        except Exception:  # telemetry must never break an answer
            pass

    def start(self, stage: str, **detail: Any) -> None:
        if self._sink is None:
            return
        if stage in self._state:
            if self._state[stage] == "start" and detail:  # e.g. loading_model while already active
                self._detail[stage].update(detail)
                self._emit(stage)
            return  # a finished stage is never replayed
        if self._active and self._active != stage and self._state.get(self._active) == "start":
            self.done(self._active)
        self._t0[stage] = time.perf_counter()
        self._state[stage] = "start"
        self._detail[stage] = dict(detail)
        self._active = stage
        self._emit(stage)

    def done(self, stage: str, **detail: Any) -> None:
        if self._sink is None:
            return
        if stage not in self._t0:
            self._t0[stage] = time.perf_counter()
        self._state[stage] = "done"
        self._detail.setdefault(stage, {}).update(detail)
        self._detail[stage].pop("loading_model", None)
        self._ms.setdefault(stage, int((time.perf_counter() - self._t0[stage]) * 1000))
        if self._active == stage:
            self._active = None
        self._emit(stage)

    def skip(self, stage: str) -> None:
        if self._sink is None or stage in self._state:
            return
        self._state[stage] = "skipped"
        self._detail[stage] = {}
        self._emit(stage)

    def finalize(self) -> None:
        """Close the active stage and mark canonical stages that never ran as skipped."""
        if self._sink is None:
            return
        for stage, st in list(self._state.items()):
            if st == "start":
                self.done(stage)
        for stage in CANONICAL:
            self.skip(stage)


class ProgressNLI:
    """Transparent NLI wrapper: announces a model load *before* the blocking first predict, nothing else."""

    def __init__(self, nli: Any, on_first_use: Callable[[bool], None]):
        self._nli = nli
        self._cb: Callable[[bool], None] | None = on_first_use

    def predict(self, premise: str, hypothesis: str) -> dict[str, float]:
        if self._cb is not None:
            cb, self._cb = self._cb, None
            fn = getattr(self._nli, "is_loaded", None)
            cb(bool(fn()) if fn else True)
        return self._nli.predict(premise, hypothesis)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._nli, name)
