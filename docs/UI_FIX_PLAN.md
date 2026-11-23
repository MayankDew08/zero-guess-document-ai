# UI fix plan — live pipeline stages + UX polish

Source: browser test of http://localhost:5173 (see findings in chat), plus a code review of the plan against `backend/app/qa/service.py`, `backend/app/main.py` and `frontend/src/`. Decisions assumed: backend streaming route is allowed; all items A + B are in scope. Change either assumption before starting.

## A. Live pipeline stages (P0)

Root cause: `POST /api/ask` (`backend/app/main.py:287`) runs the whole sync pipeline inline, so the UI has no stage data until it finishes. Cold start is 35 s+.

### A1. Backend — emit real stage events
- `backend/app/qa/service.py`: add optional `on_stage: Callable[[StageEvent], None] | None` to `ask_question` and `_ask_pipeline`. Default `None` => behaviour identical to today.
- Fire events (each `{stage, status: start|done, detail, ms}`), only from real code paths:
  1. `retrieve` — embed + BM25 hybrid (detail: candidates count)
  2. `rerank` — rerank + CRAG gate (detail: kept, max score, threshold, passed)
  3. `draft` — LLM claim drafting (detail: drafted claims; skipped when Gate 1 abstains)
  4. `resolve` — Gate 2 citation resolution (detail: resolved / rejected)
  5. `verify` — Gate 3 NLI + numeric (detail: pass / fail counts)
  6. `lineage` — amendment + contradiction analysis (detail: chains, conflicts)
- `StageEvent` Pydantic model in `backend/app/models/schemas.py`. Do NOT change `AskResponse`.

#### A1a. Model loading is NOT a leading stage (corrected)
A `models` stage fired before `retrieve` would be wrong and would almost never fire:
- `lifespan` already warms the **embedding** model at startup (`_warm` -> `rebuild_runtime_index` -> `embed`), so by the first ask it is loaded.
- The **reranker** (`bge-reranker-v2-m3`) and the **NLI** model (`mDeBERTa`) are not warmed. They load lazily in `_load()` on first use — i.e. *inside* `rerank` and *inside* `verify`. That is where most of the 35 s goes.

Pick one, and do it explicitly:
- **(a) preferred** — emit the model-load signal from inside `rerank` and `verify`: `status: "start"` with `detail: {loading_model: "<name>"}` when the provider is not yet loaded. Add a small public `is_loaded() -> bool` to `SentenceTransformerEmbeddingProvider`, `CrossEncoderRerankerProvider` and `HFNLIProvider` instead of reading `provider._model` from `qa/service.py`.
- **(b)** — also warm the reranker and NLI model in `lifespan._warm`, so the cold start moves to startup. Then no model stage is needed at all, but the first ask after boot contends with the warm task; say so in the UI instead of pretending it is fast.

Do not keep a leading `models` row that is skipped in practice.

#### A1b. The pipeline is not linear — the stage stream must account for it (corrected)
`_ask_pipeline` does not run the 6 stages once each:
- `split_question_parts` splits compound questions and loops **retrieve + rerank + draft once per part**.
- A bounded **repair round** (`_repair_claims`) can redo draft -> resolve -> verify.
- Hindi adds a translate-and-reverify step (`render_claims_in_hindi`).
- The calculator path (`is_calculation_query`) runs a contradiction scan **before** drafting, which does not fit the stage order above.

Required decision, to be fixed before writing code: **fire each stage once with an aggregate detail** (e.g. `retrieve` done with `{parts: 2, candidates: 24}`), and give the repair round its own stage key (`repair`) so it reads as an extra row rather than as stages going backwards. The UI keys rows by stage name and overwrites on a later event for the same key. Do not emit one event per part into a flat checklist.

#### A1c. `/api/ask` blocks the event loop (corrected)
`main.py:287` is `async def ask(...)` but calls the sync `ask_question` inline, so concurrent requests and `/api/health` stall for the full run. A2 fixes this for the new route only. Also change `ask` to a plain `def` so FastAPI runs it in its threadpool — behaviour-identical to the client, no new route, no signature change.

### A2. Backend — streaming route
- `POST /api/ask/stream` in `main.py`: same request body as `/api/ask`; returns `text/event-stream`.
  Run the sync pipeline in a worker thread, push events through a `queue.Queue`, emit `event: stage` per event and a final `event: result` carrying the full `AskResponse` JSON (or `event: error`).
- `StreamingResponse` is not yet imported in `main.py` (only `FileResponse, Response`) — add it.
- The `/api/ask` response shape stays untouched; its only change is the `async def` -> `def` fix in A1c.

### A3. Frontend
- `frontend/src/types/index.ts`: add the `StageEvent` type first, so `client.ts` and `App.tsx` share it.
- `frontend/src/api/client.ts`: add `askStream(question, opts, onStage)` (fetch + ReadableStream SSE parser). Additive only; fall back to `ask()` if the stream route 404s (check `res.status` before reading the body) or errors before the first event.
- `App.tsx`: `onAsk` calls `askStream`; loading `Turn` gains `stages: StageEvent[]`. Elapsed timer unchanged.
- **`patch` cannot carry stage updates (corrected).** `App.tsx:131` is `const patch = p => ({ ...x, ...p, loading: false })` — it hard-sets `loading: false`, so calling it from `onStage` would end the loading state on the first stage event. Add a separate updater (e.g. `patchStages`) that merges `stages` by stage key and leaves `loading` alone; keep `patch` for the terminal response/error only.
- `LoadingCard`: checklist — done (check + ms), active (spinner + live detail), pending (dim), skipped (dash, e.g. draft after CRAG abstain). Keep total elapsed. Contrast >= `zinc-400`. Show the cold-start line only while a stage reports `loading_model` (per A1a), not on a timer.
- No faked/timer-based progress anywhere.

### A4. Tests
- Backend: pytest with fake providers asserting stage order, CRAG-abstain skips `draft`, and `on_stage=None` leaves output identical.
- Backend: compound question ("... and what is ...") -> each stage key still appears exactly once with an aggregate detail, and a repair round appears as `repair`, not as stages replayed. This is the case A1b exists to prevent.
- Backend: SSE route test (events then `result`). Follow the existing pattern — `TestClient(main.app)` **without** the context manager, so the lifespan does not load real models.
- Fakes already exist and need no new fixtures: `FakeEmbeddingProvider`, `FakeRerankerProvider`, `FakeLLMProvider`, `FakeNLIProvider`.

## B. Frontend fixes

| # | Fix | File(s) |
|---|-----|---------|
| B1 | Scroll to the TOP of a new turn (not bottom of the answer); keep stick-to-bottom only while loading | `App.tsx` |
| B2 | Chip truncates filename only; page `p.N` is a non-shrinking suffix. Cause: the whole `{doc_name} · p.{page}` string sits in one `<span className="truncate">` | `CitationChip.tsx`, `ui.tsx` Chip |
| B3 | Expanded trace / amendment evidence scroll into view; add bottom padding above composer | `TraceCard.tsx`, `AmendmentChainCard.tsx`, `App.tsx` |
| B4 | Mobile top bar: mode select not clipped (give it `shrink-0`); workspace switch available <md — the tablist is `hidden md:flex` and exists nowhere else, so below `md` there is no way to switch workspace | `TopBar.tsx` |
| B5 | ComplianceBanner collapses to one line <md (counts only, subjects on tap) | `ComplianceBanner.tsx` |
| B6 | Themed thin scrollbars (webkit + firefox) | `index.css` |
| B7 | Remove duplicate "New chat" text span (`App.tsx:181` span next to the `:182` button) | `App.tsx` |
| B8 | Distinct aria-labels for chip vs quote buttons ("Open page p.N" / "Open quote"). Polish, not a bug — both already get a name from content + `title` | `CitationChip.tsx` |

## C. Verification (must all pass before commit)
1. `cd frontend && npx tsc --noEmit && npm run lint && npm run build`
2. `cd backend && pytest -q && ruff check .`
3. `python backend/scripts/evaluate.py --retrieval-only` — proves the new `on_stage` parameter changed nothing in `ask_question`'s behaviour. (`--full` is not needed; it is slow and contends for CPU.)
4. Browser re-run: each stage appears with real counts; the model-load detail shows while the reranker/NLI load and never otherwise; abstain skips `draft`; a compound question shows each stage once (A1b); answer scrolls to its top; chips show page at 390 px; trace expansion not clipped; workspace switchable at 390 px; Hindi + calculation clarify + BYO still work; `/api/ask` response shape unchanged.

## Order of work
A1 (incl. A1a/A1b/A1c) -> A2 -> A4 (backend, green) -> A3 -> B1–B8 -> C -> single commit.

## Risks
- Torch/model calls in a worker thread: keep the existing singleton loaders; no new model instances.
- Stage stream vs. real control flow: the per-part loop, repair round, Hindi re-verify and calculator pre-scan are the main source of misleading UI. A1b is the mitigation; the A4 compound-question test is the guard.
- Model-load timing: the reranker and NLI loads are *mid-run*, not up front (A1a). Getting this wrong makes the UI look frozen at `rerank` with no explanation.
- ~~SSE through the Vite dev origin~~ — resolved, not a risk: `CORSMiddleware` is registered app-wide (`main.py:74`) so the stream route inherits it, and `client.ts:3` calls `http://localhost:8000` directly, so no Vite proxy is in the path and there is no proxy buffering to defeat.
