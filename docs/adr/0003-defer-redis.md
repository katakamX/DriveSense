# ADR 0003 — Redis is deferred until multi-worker fan-out requires it

- **Status:** Accepted
- **Date:** 2026-08-09
- **Milestone:** 1

## Context

Redis is a common default in real-time architectures, typically for two jobs:
holding the recent telemetry window, and fanning out WebSocket messages via
Pub/Sub. It would be easy to add now on the assumption that it will be needed.

The current deployment runs **a single Uvicorn worker**. In that topology, the
process that ingests a telemetry frame is the same process that holds every
WebSocket connection.

## Decision

**No Redis in the initial system.** The recent-telemetry window is an
in-process ring buffer, and WebSocket fan-out is an in-process broadcast to a
set of connected clients.

Redis will be introduced when — and only when — this specific condition holds:

> The backend runs more than one worker process, so a client connected to
> worker A must receive telemetry ingested by worker B.

At that point Redis Pub/Sub becomes the cross-worker message bus. That change
is contained: it replaces the broadcast manager's transport and touches nothing
in the pipeline, the risk engine, or the API surface.

## Consequences

**Positive**

- One fewer service to run, configure, health-check and mock in tests.
- In-process access is faster than a network round trip, and the ring buffer is
  directly inspectable from unit tests without a running server or a fake.
- The system stays honest: no infrastructure present that isn't doing work.

**Negative**

- The backend is limited to a single worker until this decision is revisited.
  For the target workload (a small number of concurrent trips) that is not a
  practical limit, and the ceiling is documented rather than discovered.
- Live in-flight window state is lost on restart. Accepted — see ADR 0001.

## Alternatives considered

**Add Redis now, "because we'll need it."** Rejected. It would add a service
and a client dependency to solve a problem the current topology does not have.
Being able to state the precise condition that would justify it is a stronger
engineering position than having it present and idle.
