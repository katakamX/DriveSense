# contracts/ — Shared data contracts

`drivesense-contracts` holds the types that cross process boundaries. One
definition, imported by everything, so producers and consumers cannot drift
apart. Pydantic is its only runtime dependency: a telemetry producer must
never be forced to install a web or database stack to describe a data frame.

See [ADR 0005](../docs/adr/0005-shared-contracts-package.md).

| Module | Contents |
| --- | --- |
| `telemetry.py` | `TelemetryFrame`, `TripMeta`, gear encoding helpers |
| `source.py` | `TelemetrySource`, `TelemetrySink` protocols |

## `TelemetrySource` is producer-side

The backend does **not** import or implement `TelemetrySource`. Producers (the
simulator, a future OBD2 adapter) own a source and publish frames over the
network; the backend receives them and cannot tell which implementation
produced them.

## Notes

- `TelemetryFrame` is frozen and rejects unknown fields.
- Optional fields (`lat`, `lon`, `coolant_c`) default to `None`. Not every
  vehicle exposes every OBD2 PID, and a missing value must never be reported
  as a fabricated zero.
- Timestamps carry **simulated/device time**, not wall-clock time: a headless
  run compresses thirty minutes of driving into seconds and must still stamp
  frames thirty minutes apart.
- `schema_version` travels with every frame so recordings stay interpretable
  as the contract evolves.
- The package ships `py.typed`. Without it, consumers silently see every
  contract type as `Any`.

## Install

```bash
pip install -e contracts        # required before installing simulator/ or backend/
```
