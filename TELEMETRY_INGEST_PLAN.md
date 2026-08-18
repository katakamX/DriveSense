# Telemetry Ingest — investigation findings

**Status: not a new milestone. This work already exists, is migrated, wired and
tested.** It shipped as M4 (ingest + batched persistence), M5 (event detection +
WebSocket) and M9 (risk engine + sink), under the architecture ADR 0001 set out.

This document answers the three questions asked, with the evidence found, and
then lists what genuinely does *not* exist yet — which is a much smaller set
than the milestone assumed, and does not include any of the three proposed
steps.

---

## Correction to the milestone premise

The milestone as written says: *"there is no persistence layer wiring
live/simulated telemetry into it and storing the results"* and *"computing risk
in memory only."*

Both are inaccurate. `backend/app/core/risk/sink.py` is a persistence layer that
writes risk assessments to PostgreSQL, batched at five rows or five seconds
(`FLUSH_ROWS = 5`, `FLUSH_INTERVAL_S = 5.0`), with a trip-end `finalise_trip`
that stamps `trips.risk_score` / `risk_band` / `risk_engine_version` inside the
caller's transaction. Its module docstring is explicit that the accumulator is
memory *and the table is durable*:

> `_accumulators` holds the running fold for every live trip, and a restart
> wipes it. What it does *not* wipe is `risk_windows`, because every assessment
> reaches that table within five rows or five seconds of being computed.

It even handles the restart case: `_reconcile` compares the in-memory
accumulator against the persisted row count and rebuilds the summary from
`risk_windows` when memory has fallen behind.

---

## Q1 — What DB tables are needed?

**All three named as deferred already exist**, created by migrations
`0002_telemetry.py`, `0003_driving_events.py` and `0004_risk.py`.

| Proposed | Reality | Evidence |
| --- | --- | --- |
| `driving_events` | **Exists** | `app/db/models/driving_event.py`; migration `0003_driving_events.py`; written by the ingest endpoint |
| `risk_assessments` | **Exists as `risk_windows`** | `app/db/models/risk_window.py`; migration `0004_risk.py`; written by `risk/sink.py` |
| `model_predictions` | **Deliberately not a separate table** | Denormalised into `risk_windows` — see below |

### Why `model_predictions` should stay merged

`RiskWindow` already carries every model-prediction column a separate table
would hold: `model_band`, `model_score`, `model_predicted_class`,
`probabilities` (JSONB), `contributions` (JSONB top-k), and
`contributions_remainder`. They are nullable, because a rule-only assessment
genuinely has no model output.

Splitting them out would buy nothing and cost the 1:1 join on every read. It
would also break the invariant the row's docstring exists to protect — that a
stored assessment records *which engine produced it* (`risk_engine_version`,
`feature_version`, `rubric_version`, `model_version` are per-row, not per-trip),
so a historical number can always be traced to the code that computed it. A
split table would need those four columns duplicated or joined to be
meaningful.

**Recommendation: no new tables. No migration step is needed.**

---

## Q2 — REST batched POST, or WebSocket?

**Already decided, already implemented: REST batched POST.** The endpoint is
`POST /api/v1/trips/{trip_id}/telemetry/batch`
(`app/api/v1/telemetry.py`), and it is the right shape for three reasons that
are already recorded rather than open:

1. **ADR 0001 decided it.** It names the pipeline artefacts — *"driving events,
   feature windows, model predictions, risk assessments"* — and rules that
   *"PostgreSQL is a sink on the pipeline and the source of truth for history,
   not the working memory of the live system,"* with *"database writes are
   batched (roughly once per second), never one insert per frame."* The
   implemented endpoint is exactly that.

2. **`TelemetrySource` is producer-side and the backend must not import it.**
   `contracts/drivesense_contracts/source.py` says so directly:

   > The backend does **not** import or depend on `TelemetrySource`. It receives
   > frames.

   The producer (simulator today, OBD2/ELM327 later) owns the source and pushes
   batches over HTTP. That is what keeps the future OBD2 adapter a drop-in
   replacement — it implements the same protocol and POSTs to the same endpoint.
   A WebSocket ingest path would put a persistent stateful connection between
   producer and backend for no gain, and would couple the backend to producer
   liveness.

3. **WebSocket is already used, in the correct direction — outbound.**
   `WS /trips/{trip_id}/live` fans results *out* to the browser
   (`app/core/live/`). Ingest in, results out. Adding a second inbound socket
   would duplicate a working path.

**Recommendation: no change. The REST/WS split is correct and shipped.**

---

## Q3 — Step-by-step breakdown

Not applicable — there is nothing to break down. Each proposed step is already
done:

| Proposed step | Status |
| --- | --- |
| One migration / model | Done — `0002`, `0003`, `0004` |
| One ingest endpoint | Done — `POST /trips/{trip_id}/telemetry/batch` |
| One wiring-into-risk-engine step | Done — endpoint calls `buffer_append` + `ensure_started`; the 1 Hz tick scores and calls `sink.enqueue` / `flush_if_due`; `trips.PATCH` calls `sink.finalise_trip` |

### What the existing endpoint does, in order

1. 404s on an unknown trip.
2. Inserts `Telemetry` rows (raw frame preserved as JSONB), `flush()`es to get
   IDs for FK linkage.
3. Runs `detect_events` with **per-trip state**, so a brake spanning two batches
   is one event, and inserts `DrivingEvent` rows.
4. Commits.
5. Appends to the ring buffer (from the payload, not the rows — the buffer wants
   extended fields like yaw rate that have no telemetry column) and starts the
   1 Hz tick on first batch.
6. Publishes telemetry and event frames to the live WebSocket.

---

## What actually *is* missing

Two real gaps, both small, neither one a milestone:

1. **No dedicated endpoint test for telemetry ingest.** There is no
   `test_telemetry_ingest.py`. The endpoint is exercised only as setup in
   `test_windowing.py:503`, `test_live_reconnect.py:140` and
   `test_route_protection.py:143`, and **no test asserts on the persisted
   `Telemetry` or `DrivingEvent` rows themselves** (grep for `select(Telemetry)`
   / `select(DrivingEvent)` across `backend/tests/` returns nothing). The
   persistence works, but its endpoint-level contract is covered only
   incidentally. A focused test file would be roughly one step of work.

   Note this is a *test* gap, not a behaviour gap — `test_risk_sink.py` and
   `test_sink_recovery.py` do cover the risk-persistence layer directly.

2. **No read endpoints for the persisted history.** README states this is
   deliberate and scheduled:

   > There are deliberately **no read endpoints for telemetry frames, driving
   > events or risk windows yet** — the live path is the WebSocket, and the
   > historical read surface arrives with the dashboard pages in M12.

   So the data is being written and nothing reads it back yet. That is M12's
   job, and M12 is blocked on the same thing flagged in the last session: the
   eight dashboard pages are never enumerated anywhere in the repo.

---

## Recommendation

Do not open this as a milestone. Two options that are real:

- **Close the test gap** (small, well-scoped, no product decision needed): add
  `backend/tests/test_telemetry_ingest.py` asserting the endpoint's persistence
  contract — rows written, event linkage via `telemetry_id`, cross-batch event
  continuity, 404 on unknown trip.
- **Scope M12** (needs a product decision): enumerate the eight dashboard pages,
  which then defines the read endpoints the persisted telemetry/events/risk
  windows need. This is the same blocker recorded in `SESSION_LOG.md` item 6.

No code was written for this investigation.
