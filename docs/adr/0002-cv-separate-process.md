# ADR 0002 — Computer vision runs as a separate process

- **Status:** Accepted
- **Date:** 2026-08-09
- **Milestone:** 1 (decision), 10 (implementation)

## Context

Driver monitoring analyses a camera stream at 10–15 FPS to estimate drowsiness
and distraction. The natural-looking option is to run this inside the FastAPI
application, alongside telemetry ingest and the API.

Three properties of the workload argue against that:

1. Frame analysis is **CPU-bound and synchronous**. Running it inside the async
   event loop starves telemetry ingest and WebSocket broadcast; running it in a
   thread pool contends for the GIL with the same effect at lower volume.
2. It needs **camera hardware access**. Passing a webcam into a container is
   platform-specific and unreliable, particularly on Windows and macOS.
3. It is **optional**. The rest of the system must work without a camera.

## Decision

Computer vision is a standalone process (`cv/`) that owns the camera, performs
landmark detection and temporal aggregation locally, and pushes an aggregated
`DriverStateFrame` to the backend at **1 Hz** via `POST /api/v1/ingest/driver-state`.

Raw frames never leave the CV process. Only derived scalars — drowsiness,
distraction, PERCLOS, blink rate, `face_detected` — cross the boundary.

## Consequences

**Positive**

- The FastAPI event loop stays free for I/O; a slow or crashed CV process
  cannot degrade telemetry ingest or the live dashboard.
- The CV process can run natively on the driver's machine (with camera access)
  while the backend runs in Docker — which is what a live demo actually needs.
- Bandwidth and privacy both benefit: no video is transmitted or stored.
- The 15 FPS analysis loop is decoupled from the 1 Hz reporting rate, so the
  two can be tuned independently.

**Negative**

- One more process to start, document and supervise.
- The `DriverStateFrame` contract exists in two places (`cv/contracts.py` and
  the backend schema) and must be kept in sync. Mitigated by generating both
  from the backend's OpenAPI schema once Milestone 3 lands.
- Absent CV means a missing risk-engine input. Handled deliberately: the risk
  engine renormalises over available signals and marks the assessment
  `degraded`, rather than imputing a neutral drowsiness score.

## Later exception

[ADR 0008](0008-browser-camera-monitor-mode.md) knowingly departs from this
decision for one specific case: a zero-setup browser demo with no local
process to run `cv/` on. That path accepts the trade-offs this ADR rejects
(frames crossing the network, in-process CPU contention) for that narrow
use only; the decision above still governs the vehicle-mounted deployment.

## Alternatives considered

**In-process background thread.** Rejected: GIL contention and camera access
in the API container.

**Separate microservice with a message broker.** Rejected as overengineering.
A 1 Hz HTTP POST is entirely adequate; a broker adds infrastructure without
solving a problem this system has.
