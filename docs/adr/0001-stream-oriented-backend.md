# ADR 0001 — The backend is stream-oriented, not CRUD-oriented

- **Status:** Accepted
- **Date:** 2026-08-09
- **Milestone:** 1

## Context

DriveSense ingests vehicle telemetry at roughly 1–10 Hz and must derive driving
events, a behaviour classification, and a risk score from it with low enough
latency to drive a live dashboard.

The default shape for a FastAPI + PostgreSQL project is CRUD: routes read and
write rows, and anything analytical becomes a query or a batch job. Applied
here, that shape would mean writing each telemetry frame to the database and
then re-reading recent rows whenever a derived value is needed.

## Decision

The core abstraction is a **telemetry frame flowing through an in-process
pipeline**, not a row in a table. Every derived artefact — driving events,
feature windows, model predictions, risk assessments — is produced by that
pipeline as frames arrive. PostgreSQL is a **sink** on the pipeline and the
source of truth for history, not the working memory of the live system.

Concretely:

- A bounded in-memory ring buffer per active trip holds the recent window
  (~30 s) that event detection and feature extraction read from.
- Database writes are **batched** (roughly once per second), never one insert
  per frame.
- Derived values are computed once, on arrival, and fanned out to both the
  WebSocket broadcast and the persistence layer.

## Consequences

**Positive**

- Live-path latency is bounded by in-memory work, not by database round trips.
- Batched inserts are roughly two orders of magnitude cheaper than row-at-a-time
  inserts at 10 Hz, which is the difference between a system that sustains a
  30-minute trip and one that does not.
- Feature extraction reads the same in-memory window that training will read
  from a file, which keeps training and serving aligned (see ADR 0004).

**Negative**

- Live state is held in process memory, so a backend restart loses the current
  in-flight window. Accepted: persisted telemetry is unaffected, and the window
  refills within ~30 s.
- The pipeline must apply backpressure explicitly. Slow WebSocket clients get
  dropped frames (latest-value-wins) rather than an unbounded queue.
- Horizontal scaling requires shared state, which is the exact condition under
  which Redis becomes justified (see ADR 0003).

## Alternatives considered

**Write-then-query (pure CRUD).** Rejected: adds a database round trip to every
derived value on the hot path, and makes the 10 Hz write pattern the bottleneck.

**External stream processor (Kafka / Flink).** Rejected as disproportionate.
The workload is a handful of concurrent trips, not a distributed firehose; the
operational cost of a broker is not repaid at this scale.
