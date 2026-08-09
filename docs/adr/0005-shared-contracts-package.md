# ADR 0005 — A shared contracts package, and `TelemetrySource` is producer-side

- **Status:** Accepted
- **Date:** 2026-08-09
- **Milestone:** 2
- **Amends:** [ADR 0002](0002-cv-separate-process.md)

## Context

`TelemetryFrame` is about to become the most widely shared type in DriveSense.
The simulator emits it now; an OBD2 adapter will emit it later; the backend
will parse it from Milestone 4; the CV service has an analogous
`DriverStateFrame`. Wherever a type like this is defined twice, it drifts.

Two placements were considered.

**In the backend** (`backend/app/schemas/`), with producers importing the
backend package. This inverts the dependency: a telemetry producer would have
to install FastAPI, SQLAlchemy and psycopg in order to describe a data frame.
It also contradicts [ADR 0001](0001-stream-oriented-backend.md), which treats
the producer as an external process that the backend knows nothing about.

**In the producer**, with the backend duplicating it at Milestone 4. This is a
guaranteed future refactor and an invitation to drift in the meantime.

## Decision

A third, standalone package: **`contracts/`**, distributed as
`drivesense-contracts`, whose only runtime dependency is Pydantic.

```
contracts/drivesense_contracts/
├── telemetry.py     TelemetryFrame, TripMeta, gear encoding
├── source.py        TelemetrySource, TelemetrySink protocols
└── py.typed         so consumers actually get the types
```

Both `simulator/` and (from Milestone 4) `backend/` depend on it via a local
path install. Nothing in it imports a web framework, a database driver, or
pygame.

### `TelemetrySource` is a producer-side abstraction

This is the part most likely to be misread, so it is stated explicitly:

> The backend does **not** import, depend on, or implement `TelemetrySource`.

A producer process owns a source and pumps its frames into sinks:

```
SimulatorTelemetrySource ─┐
                          ├─► frames() ─► TelemetrySink ─► file (M2)
OBD2TelemetrySource ──────┘                             └─► HTTP/WS → backend (M4)
```

The backend receives frames over the network and cannot tell which
implementation produced them. Treating `TelemetrySource` as a backend
interface would reintroduce exactly the coupling ADR 0001 exists to prevent —
the backend would then care where telemetry comes from.

### Amendment to ADR 0002

ADR 0002 proposed generating the CV service's `DriverStateFrame` contract from
the backend's OpenAPI schema. That is superseded: `DriverStateFrame` will be
defined in `drivesense_contracts` alongside `TelemetryFrame`, and the CV
service will depend on this package. The reasoning in ADR 0002 for keeping CV
in a separate process is unaffected — only the ownership of the contract
changes.

## Consequences

**Positive**

- One definition, one validation surface, no drift between producer and
  consumer. Pydantic validates identically on both sides of the wire.
- Producers stay lightweight. The simulator installs Pydantic and pygame-ce,
  not a web stack.
- `py.typed` means consumers get real types. Without it, mypy silently degrades
  every contract type to `Any` in every consuming package — which is exactly
  what happened before the marker was added, and it hid nothing useful.
- The future OBD2 source and CV service inherit the contract for free.

**Negative**

- A third Python package to install in development. Mitigated by installing it
  first from a path (`pip install -e ../contracts`), documented in the README,
  the Makefile and CI.
- Versioning discipline is now required: `TelemetryFrame` carries a
  `schema_version` field so a recording made today remains interpretable after
  the contract evolves.

## Alternatives considered

**Duplicate the model in each package.** Rejected — the drift this causes is
silent, and it is the same failure mode ADR 0004 exists to prevent for
features.

**Generate everything from OpenAPI.** Reasonable for the *TypeScript* client,
which is still the plan for the frontend. Poor fit here: it would make the
simulator's contract depend on the backend being able to boot.
