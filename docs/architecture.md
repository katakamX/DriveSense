# DriveSense — Architecture

This document is the reference for how DriveSense is put together. Decisions
with meaningful trade-offs are recorded separately as ADRs in [`adr/`](adr/).

## Runtime topology

```
┌───────────────────────┐        ┌──────────────────────┐
│  Telemetry Producer   │        │   CV Service         │
│  (simulator | OBD2)   │        │  camera → driver     │
│  separate process     │        │  state, 10–15 FPS    │
└──────────┬────────────┘        └──────────┬───────────┘
           │ TelemetryFrame @1–10 Hz        │ DriverStateFrame @1 Hz
           ▼                                ▼
┌──────────────────────────────────────────────────────────┐
│                   FastAPI Backend                        │
│                                                          │
│  Ingest ──► Ring buffer ──► Feature extraction           │
│                    │                                     │
│                    ├──► Event detector  (thresholds)     │
│                    ├──► Behaviour model (XGBoost)        │
│                    └──► Driver state    (from CV)        │
│                              │                           │
│                              ▼                           │
│                     Risk engine (pure, versioned)        │
│              ┌───────────────┼───────────────┐           │
│              ▼               ▼               ▼           │
│         WS broadcast    Batched writes   REST API        │
└───────────────────────────┬──────────────────────────────┘
                ┌───────────┴───────────┐
                ▼                       ▼
          PostgreSQL              React Dashboard
```

## Component responsibilities

| Component | Responsibility | Milestone |
| --- | --- | --- |
| `contracts/` | `TelemetryFrame` and the producer-side `TelemetrySource`/`TelemetrySink` protocols. Pydantic only. | 2 |
| `simulator/` | Interactive manual-transmission vehicle simulator. Pure physics core, pygame confined to input and rendering. A **client** of the backend, not part of it. | 2 |
| `backend/app/api` | HTTP and WebSocket surface. Validation and serialisation only — no domain logic. | 3, 5 |
| `backend/app/db` | SQLAlchemy models, migrations, repositories for non-trivial queries. | 3 |
| `backend/app/core/windowing` | Bounded in-memory ring buffer per active trip. | 4 |
| `backend/app/core/events` | Threshold-based driving-event detection. Deterministic and configurable — not ML. | 5 |
| `backend/app/core/features` | Telemetry window → feature vector. **The only implementation** (ADR 0004). | 7 |
| `backend/app/core/risk` | Pure, versioned, explainable risk scoring, and the rule layer both it and the offline labeller read (ADR 0007). One impure module, `sink`, batches the writes. | 9 |
| `backend/app/ml` | Model loading and inference, with rule-only fallback when no artefact is present. | 8 |
| `ml/` | Offline pipeline: clean → window → featurise → label → split → train → evaluate. | 7, 8 |
| `cv/` | Camera capture, facial landmarks, drowsiness estimation. Separate process (ADR 0002). | 10 |
| `frontend/` | React dashboard. Design tokens first, then components. | 6, 12 |

## Key design decisions

- **Stream-oriented backend.** Telemetry frames flow through an in-process
  pipeline; PostgreSQL is a sink, not working memory. → [ADR 0001](adr/0001-stream-oriented-backend.md)
- **CV out of process.** CPU-bound work and camera access stay off the async
  event loop. → [ADR 0002](adr/0002-cv-separate-process.md)
- **No Redis initially.** Single-worker topology makes in-process fan-out
  sufficient; the condition that would justify Redis is stated explicitly.
  → [ADR 0003](adr/0003-defer-redis.md)
- **One feature implementation.** Training/serving skew is prevented
  structurally and asserted in CI. → [ADR 0004](adr/0004-shared-feature-engineering.md)
- **Shared contracts package.** `TelemetryFrame` has one definition;
  `TelemetrySource` is producer-side and the backend never imports it.
  → [ADR 0005](adr/0005-shared-contracts-package.md)
- **Rules gate the risk engine's top band.** `HIGH_RISK` is emitted only when
  the rule layer independently reaches it; the model alone caps at
  `AGGRESSIVE`. Measured `HIGH_RISK` precision of 0.105 on real telemetry is
  the reason, and the condition for removing the gate is stated.
  → [ADR 0007](adr/0007-risk-engine-rule-gating.md)
- **Plain PostgreSQL.** TimescaleDB is considered only if load testing at
  Milestone 4 shows it is needed.
- **No authentication.** DriveSense is a single-tenant demonstration system.
  Adding auth would be scope without insight.

## Frequency budget

| Stage | Rate |
| --- | --- |
| Telemetry ingest | 1–10 Hz |
| Event detection | every frame |
| Feature extraction + inference + risk | 1 Hz |
| Telemetry push to dashboard | 10 Hz |
| Risk push to dashboard | 1 Hz |
| Database writes | batched, ~1 Hz |

Target end-to-end ingest → browser latency: **< 150 ms**. Measured at
Milestone 14 (`bench/`, `python -m drivesense_bench`): real-time-paced
simulated trips POST 10 Hz telemetry over HTTP while a real WebSocket client
times each frame's round trip, ramping concurrent trips until something
breaks. Run against both the local dev backend and the Docker Compose stack
(single backend process, default-configured Postgres pool, on one
16-core dev machine — not a production topology):

| Concurrent trips | p50 (dev / docker) | p95 (dev / docker) | p99 (dev / docker) |
| --- | --- | --- | --- |
| 1  | 56.0 / 13.4 ms | 85.9 / 17.1 ms   | 109.7 / 58.5 ms  |
| 2  | 15.6 / 16.5 ms | 80.0 / 32.3 ms   | 151.2 / 43.7 ms  |
| 5  | 23.9 / 26.0 ms | 108.2 / 41.0 ms  | 214.2 / 57.7 ms  |
| 10 | 32.7 / 51.3 ms | 116.4 / 89.8 ms  | 209.1 / 180.8 ms |
| 20 | — | — (every request failed) | — |

**Through 10 concurrent trips, p95 stays under the 150 ms target** (worst
observed: 116.4 ms, dev). **At 20 concurrent trips the system does not
degrade gracefully past the target — it collapses outright**: every
telemetry POST fails. The cause, identical in both environments:

```
sqlalchemy.exc.TimeoutError: QueuePool limit of size 5 overflow 10 reached,
connection timed out, timeout 30.00
```

`app/db/session.py` creates the async engine with no `pool_size`/
`max_overflow` override, so it runs on SQLAlchemy's defaults — 15
connections total. Each concurrent trip needs one for its telemetry batch
insert and another for its own 1 Hz risk tick; demand exceeds the pool
somewhere between 10 and 20 concurrent trips, and requests queue for the
pool's 30 s timeout before failing. This is a connection-pool configuration
finding, not a dev-only artifact (the Docker Compose stack fails the same
way), and not something this milestone fixes — tuning the pool is a future
ops/perf decision.

## Milestones

Milestones 1–10 are the core product. Real-time hardening, the remaining
dashboard pages (11–12), and benchmarking (14) are complete; OBD2 hardware
(13) and deployment polish (15) follow and must not block the core.

| # | Milestone | Exit criterion |
| --- | --- | --- |
| 1 | Architecture, scaffold, Docker skeleton, CI | Stack starts; CI green ✅ |
| 2 | Interactive vehicle simulator + shared contracts | Driveable manual-transmission model; deterministic headless runs; JSONL recording ✅ |
| 3 | FastAPI + PostgreSQL + migrations + CRUD | Core entities, OpenAPI published |
| 4 | Ingest pipeline + batched persistence | 10 Hz sustained, verified in DB |
| 5 | Event detection + thin WebSocket path | Live values in the browser |
| 6 | Design system + Dashboard + Live Drive | Real UI on real live data |
| 7 | Dataset + shared feature engineering | Feature parity test passes |
| 8 | Model training + honest evaluation | Committed metrics and model card |
| 9 | Risk engine + explainability | Golden and property tests pass ✅ |
| 10 | CV driver monitoring | 15 FPS standalone; degrades cleanly |
| 11 | Real-time hardening | Survives backend restart without UI breakage |
| 12 | Remaining dashboard pages | The seven pages enumerated in `M12_PLAN.md` functional ✅ |
| 13 | OBD2 / ELM327 integration | Real device produces a trip |
| 14 | Test hardening + benchmarking | Measured latency and throughput ✅ |
| 15 | Deployment polish + documentation | One-command startup, demo |

## Honest ML methodology

There is no public dataset labelled with DriveSense's behaviour classes
(CALM / NORMAL / AGGRESSIVE / HIGH_RISK). Labels are therefore produced by a
**documented, deterministic rubric** over feature windows — this is weak
supervision from a rule-based labeller, not human-annotated ground truth, and
it will be stated as such in the model card.

Two commitments follow:

- Train/test splits are made **by trip and by driver profile**, never by random
  row. Overlapping windows from one trip appearing on both sides of the split
  inflates accuracy into a meaningless number.
- Results are validated against **real public telemetry** the rubric never saw,
  to test whether the model generalises beyond the rules or has merely
  memorised them.

No metric appears in this repository that was not produced by a committed,
reproducible pipeline.
