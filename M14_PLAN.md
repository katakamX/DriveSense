# M14: Test Hardening + Benchmarking — Investigation

## What M14 was originally scoped to cover

Two sources name it, and they agree:

| Source | Wording |
|---|---|
| `docs/architecture.md` milestone table | `14 \| Test hardening + benchmarking \| Measured latency and throughput` |
| `README.md` milestone table | `14 \| Test hardening + benchmarking \| ` (no exit criterion column filled) |

Two further statements pin the target down:

- `docs/architecture.md:88` — "Target end-to-end ingest → browser latency: **< 150 ms**, to be measured at Milestone 14 and reported with real numbers."
- `README.md:340-342` — "The end-to-end latency target (ingest → browser, < 150 ms) is stated in the architecture document but **has not been measured yet** — that is M14, and it will be reported with real numbers or not at all."

**So M14 is performance benchmarking, not model-accuracy benchmarking.** That
matters because "benchmarking" is ambiguous in the abstract but not here:
accuracy benchmarking was M8's job and is already done (see below). Nothing in
any document assigns model metrics to M14.

Also relevant — `docs/architecture.md:80-86` gives the rates the system is
designed around, which are the throughput figures M14 has to confirm the
implementation actually sustains:

| Stage | Design rate |
|---|---|
| Telemetry ingest | 10 Hz |
| Feature extraction + inference + risk | 1 Hz |
| Telemetry push to dashboard | 10 Hz |
| Risk push to dashboard | 1 Hz |
| Database writes | batched, ~1 Hz |

## What already exists

**Model accuracy benchmarking: complete, and not M14's problem.**
`ml/pipelines/evaluate.py` is a full evaluation harness — macro-F1 headline,
balanced accuracy, per-class precision/recall/F1 with support counts, the full
4×4 confusion matrix (raw and row-normalised), `HIGH_RISK` recall called out
separately, majority-class baseline printed alongside every model number, and a
degenerate-outcome guard that flags zero-recall classes and any model failing to
beat the baseline. Results are committed in `ml/reports/m8-evaluation.md` and
`docs/model-card.md`. `evaluate_predictions` is model-agnostic (takes two label
sequences), so it already covers the rubric baseline, the majority baseline, the
tree and the logistic regression comparably. **Nothing to add here for M14.**

**Correctness test suites: substantial.** 43 backend test modules (368 passed, 2
skipped at last full run), plus `ml/tests` (8 modules incl. a feature-parity test
against the backend), `cv/tests`, `contracts/tests`, `simulator` (96 tests, all
headless), and `frontend` vitest (26 tests). Risk-engine golden fixtures and
Hypothesis property tests already exist (`test_risk_golden.py`,
`test_risk_properties.py`). CI runs at `.github/workflows/ci.yml`.

## What is missing

1. **No load-testing or perf-testing setup anywhere in the repo.** No locust, no
   k6, no `pytest-benchmark`, no `wrk`/`ab` scripts, no timing harness. Searched
   the full tracked file list for `bench|perf|latency|load|locust|k6` — the only
   hits are `ml/pipelines/evaluate.py`, `ml/reports/m8-evaluation.md`,
   `backend/app/ml/loader.py` and `backend/tests/test_ml_loader.py`, all
   accuracy/model-loading, none of them performance.

2. **No telemetry producer that actually posts to the backend.** This is the
   blocking finding. `POST /trips/{trip_id}/telemetry` is exercised only by
   `backend/tests/test_telemetry.py` via `TestClient`. The simulator's sinks
   (`simulator/drivesense_sim/telemetry/sinks.py`) are `NullSink`, `MemorySink`
   and `JsonlSink` — **there is no HTTP sink**. The only tracked HTTP client
   pointed at the backend is `cv/client.py`, which posts driver-state frames to
   `/ingest/driver-state`, not telemetry. So a load generator cannot simply
   "run N simulators against the API" today; that path does not exist yet.

3. **No instrumentation on the latency path.** The ingest → browser hop spans
   `api/v1/telemetry.py` → `core/windowing` → `core/features` → `core/risk` →
   `core/live/broadcaster.py` → `api/v1/live.py` (WebSocket). No timestamps are
   recorded at stage boundaries, so end-to-end latency is currently not
   observable even manually.

4. **No coverage measurement.** No `pytest-cov` in `backend/pyproject.toml`'s dev
   extras, no coverage config, no coverage step in CI. If "test hardening" is
   meant to include a coverage floor, the tooling isn't there.

## Scope decision required — this is your call

The milestone name has two halves. The benchmarking half is well-specified by
the < 150 ms target and the rate table. **The "test hardening" half is not
specified anywhere.** I am not picking between these; below are the options as I
read them.

### Option A — Benchmarking only (matches the stated exit criterion exactly)

Build the load generator, instrument the latency path, measure, publish numbers.
Exit criterion "Measured latency and throughput" is satisfied literally. Treat
"test hardening" as already discharged by the existing suites.

*Argument for:* the exit criterion names only latency and throughput. The suites
are already large and green.
*Argument against:* leaves the milestone's own title half-unaddressed.

### Option B — Benchmarking + coverage/robustness hardening

Option A, plus: add `pytest-cov`, measure and report actual coverage, identify
and fill the genuinely untested paths, add a CI coverage gate.

*Argument for:* "test hardening" plainly means something, and coverage is the
conventional reading.
*Argument against:* coverage percentage is a weak signal and a gate can invite
box-ticking tests. Would need a stated floor you're willing to defend.

### Option C — Benchmarking + end-to-end integration testing

Option A, plus a real end-to-end test: a trip driven through the actual HTTP API
against a real Postgres and a real WebSocket client, asserting the browser
receives the right messages. Currently every backend test uses `TestClient`
against an overridden `get_db`; nothing exercises the deployed Docker stack.

*Argument for:* the load generator from Option A is most of an e2e harness
already, so the marginal cost is low. Catches the class of bug the Docker
healthcheck failure was (works locally, broken in the container).
*Argument against:* e2e tests are slow and flaky; needs a decision on whether it
runs in CI or on demand.

### Also undecided within the benchmarking half

- **Which latency to headline.** The < 150 ms target is ingest → browser
  end-to-end. Per-endpoint REST latency (the dashboard pages) is a different
  number and not mentioned in any document. Measure both, or just the stated one?
- **What load level counts as passing.** "Throughput" has no target number
  anywhere. Concurrent trips is the obvious axis (each is 10 Hz telemetry + a
  WebSocket). No document says whether the answer should be 5, 50, or 500.
- **Where it runs.** Numbers from a Windows dev laptop and numbers from the
  Docker stack will differ, and neither is a production figure. The README
  promises "real numbers or not at all", so the measurement environment has to be
  stated alongside the result.

## Build plan

Steps 1–6 are Option A and are common to all three options. Steps 7+ are the
option-specific additions. One step per session, stopping after each.

### Step 1 — HTTP telemetry sink for the simulator *(backend: none; simulator only)*
Add an `HttpSink` alongside the existing sinks in
`simulator/drivesense_sim/telemetry/sinks.py`, posting batches to
`POST /trips/{trip_id}/telemetry`. Must respect the existing headless-purity
constraint (`simulator/tests/test_headless_purity.py` — the telemetry path must
not import pygame). Needs auth: the endpoint's gating has to be checked and the
sink given a session cookie or whatever the endpoint actually requires.
*Exit:* one headless simulator run lands real rows in the database over HTTP.

### Step 2 — Stage timestamps on the latency path *(backend)*
Record monotonic timestamps at the stage boundaries named in finding 3 and carry
them through to the outgoing `LiveMessage`, behind a setting that is off by
default. Deciding whether this ships as a debug-only field or as permanent
structured logging is part of the step.
*Exit:* a single frame's ingest → publish latency is readable from one place.

### Step 3 — WebSocket receive-side timer *(new bench harness)*
A small client that subscribes to `/trips/{id}/live` and records arrival time per
message, so the browser end of "ingest → browser" is actually measured rather
than inferred from server-side numbers.
*Exit:* end-to-end latency for one trip, one number, reproducible.

### Step 4 — Load generator *(new bench harness)*
Drive N concurrent trips (Step 1's sink) with M concurrent WebSocket subscribers
(Step 3's client), ramping N until something degrades. Plain asyncio rather than
locust/k6 unless there's a reason to add a dependency — the producers and
consumers are both already Python and already exist by this point.
*Exit:* latency and throughput as a function of concurrent trips.

### Step 5 — Run against the Docker stack
Re-run Step 4 against `docker compose up` rather than the local uvicorn dev path,
since that is the configuration the numbers should describe.
*Exit:* two datasets, dev and Docker, with the difference explained.

### Step 6 — Report
`ml/reports/`-style document (suggest `docs/m14-benchmark.md`) stating hardware,
configuration, method, and results. Update `docs/architecture.md:88` and
`README.md:340-342` — both currently say the target "has not been measured yet",
and both must change, including if the 150 ms target turns out to be missed.
*Exit:* M14 benchmarking half complete; README no longer claims an unmeasured
target.

### Step 7 — *(Option B only)* Coverage
Add `pytest-cov`, report actual coverage per package, fill the gaps worth
filling, then decide on a CI gate and a floor.

### Step 7' — *(Option C only)* End-to-end test
Promote Step 4's harness into a small e2e suite run against the Docker stack, and
decide whether it runs in CI or on demand.

## Open questions for you

1. **Option A, B, or C?**
2. **Throughput target** — how many concurrent trips should the system be claimed
   to sustain? There is no number in any document.
3. **Step 2's instrumentation** — permanent (structured logging, useful in
   production) or benchmark-only scaffolding removed afterwards?
4. Should per-endpoint REST latency for the M12 dashboard pages be measured too,
   or is the ingest → browser path the only one M14 owes a number for?
