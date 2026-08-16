# ADR 0008 — Browser-camera driver monitor is an accepted exception to ADR 0002

- **Status:** Accepted
- **Date:** 2026-08-16
- **Milestone:** 11

## Context

[ADR 0002](0002-cv-separate-process.md) put driver-state detection in its own
process (`cv/`) because the workload is CPU-bound, needs camera hardware
access, and is optional. That reasoning is sound for the vehicle-mounted
deployment: a camera physically wired to the vehicle, with a machine free to
run a dedicated Python process next to it.

It does not cover every case this product needs. A dispatcher who wants to
spot-check a driver from a phone or a laptop, with no local process to
install and no camera wired to anything, cannot use `cv/` at all — there is
nothing to install it on. `app/core/monitor` and the
`/ws/driver-monitor/{driver_code}` socket
(`backend/app/api/v1/driver_monitor.py`) exist for exactly that case: a
browser captures frames and streams them to the backend, which decodes and
scores them with MediaPipe in-process.

This is not a replacement for `cv/`. `cv/` remains the only sanctioned path
for the vehicle-mounted, hardware-integrated deployment, and nothing here
changes that. This ADR exists because the code's own package docstring said
it needed one before shipping — see `app/core/monitor/__init__.py`.

## Decision

The browser-camera path is a deliberate, scoped exception to ADR 0002, for
one use case only: a zero-setup demo or spot-check from an ordinary browser,
where no separate CV process is installable. It knowingly gives up both
properties ADR 0002's decision was built on:

- **Raw frames cross the network.** They are decoded, scored, and discarded —
  never written to disk or the database — but they do leave the client and
  reach the FastAPI worker. ADR 0002's "raw frames never leave this process"
  guarantee does not hold here, and no amount of care in `app/core/monitor`
  makes it hold. Anyone routing sensitive footage through this path over an
  untrusted network is accepting that exposure.
- **MediaPipe runs inside the API worker.** Every call is dispatched to a
  thread pool so the event loop keeps serving other requests, but the CPU
  itself is shared with telemetry ingest and the risk engine, and
  [ADR 0003](0003-defer-redis.md) pins the deployment to a single worker
  process. There is no isolation between a slow frame and a slow ingest
  batch — they compete for the same cores.

Neither trade-off makes the feature wrong; both make it a different
deployment shape from the one ADR 0002 describes, accepted here for a
specifically low-stakes use case (a manual demo, not unattended production
monitoring of a moving vehicle).

### When to reconsider

This mode is accepted as-is only while its CPU cost stays incidental. The
concrete signal to revisit: **if telemetry ingest p99 latency measurably
regresses while a driver-monitor socket is active** — worth instrumenting as
a specific, comparable metric rather than inferred from general dashboard
noise — the answer is not to keep tuning the thread pool. It's to move this
path out of the API process (its own worker, queued via the browser same as
today) rather than pretend the single-process trade-off still holds. No
such regression has been measured yet; this is a threshold to watch for, not
a finding.

### Known gap: no authentication

The socket accepts any `driver_code` the client asserts — there is no
session or token tying a connection to a real logged-in dispatcher. This is
accepted for now because the feature is a demo/spot-check path, not a
production monitoring channel with an audit trail. It must be closed before
this path is used for anything beyond that. Out of scope for this ADR;
tracked here so it isn't forgotten rather than solved here.

## Consequences

**Positive**

- No second process to install, document, or supervise for a demo — works
  from any device with a browser and a camera.
- Isolated in its own package (`app/core/monitor`) and router; does not
  share code with, or modify, `cv/`.

**Negative**

- Privacy and process-isolation properties ADR 0002 relies on for the
  in-vehicle deployment do not apply to this path. Documented here so that
  gap is a decision, not an oversight.
- A second `DriverStateFrame`-shaped contract now exists conceptually
  alongside `cv/`'s, though the wire schemas differ (`MonitorReading` here is
  per-frame; `cv/`'s is a 1 Hz aggregate) — see
  `backend/app/schemas/monitor.py` vs. `cv/contracts.py`. No shared code, so
  no drift risk beyond the two staying conceptually distinct.
- No authentication on the socket (see above).

## Alternatives considered

**Give the browser path its own worker process too, symmetric with `cv/`.**
Rejected for now: the entire point of this mode is zero local setup. A
second process to run defeats it. If the CPU-contention signal above is ever
tripped, this is the fallback — but it is not worth building pre-emptively
for a path whose whole value is not needing a second process.

**Block the feature entirely until it can be made ADR-0002-compliant.**
Rejected: the vehicle-mounted and zero-setup-demo cases have genuinely
different constraints, and forcing one architecture onto both would either
break the demo case (no process to install) or weaken the vehicle case
(accepting frame egress it doesn't need to accept). Documenting the
divergence, as this ADR does, is preferred over pretending one shape fits
both.
