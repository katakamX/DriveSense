# simulator/ — Interactive vehicle simulator

A lightweight manual-transmission driving simulator whose purpose is to
produce **believable telemetry from a genuinely simulated vehicle**. It is not
a game, and no telemetry value is ever generated independently of vehicle
state.

```
Pygame input ─┐
              ├─► ControlInput ─► Vehicle.step() ─► VehicleState ─► TelemetryFrame ─► sink
Scripted   ───┘                   (fixed 120 Hz)                       (10 Hz)
```

## Running it

```bash
python -m drivesense_sim                 # interactive window
python -m drivesense_sim --record        # interactive, recording from the start
python -m drivesense_sim --headless      # scripted demo drive, no window, records JSONL
python -m drivesense_sim --stall         # enable engine stalling (off by default)
python -m drivesense_sim --noise         # enable sensor noise (off by default)
```

### Posting to the backend

`--post-to` swaps the JSONL sink for `HttpSink`, which batches frames to
`POST /api/v1/trips/{trip_id}/telemetry/batch`:

```bash
python -m drivesense_sim --headless --drive normal --duration 30 \
    --post-to http://localhost:8000 \
    --backend-trip-id 005469ab-e9e5-4165-b1b2-684f79bb6998
```

`--backend-trip-id` is a **backend trip UUID**, not the recording id — the row
has to exist already, created by staff via `POST /trips` with a driver and a
vehicle. The two ids are unrelated and neither can be derived from the other.

A headless run is not paced in real time: it produces frames as fast as the CPU
allows, so thirty seconds of simulated driving posts in about five wall-clock
seconds. That is what makes bulk dataset generation practical, but it means the
backend's 1 Hz windowing tick sees far fewer seconds than the telemetry claims,
and a run like this cannot be used to measure latency.

## Controls

| Key | Action |
| --- | --- |
| `W` | throttle |
| `S` | brake |
| `A` / `D` | steer left / right |
| `Shift` | gear up |
| `Ctrl` | gear down |
| `R` | toggle reverse |
| `N` | neutral |
| `Space` | clutch |
| `F1` | toggle telemetry recording |
| `Esc` | quit |

Pedals ramp rather than snapping between 0 and 1, so a keyboard produces
analog-like traces instead of square waves — square-wave throttle would make
the feature engineering in Milestone 7 degenerate. Gear changes are
edge-triggered on key *press*, so holding `Shift` shifts once, not six times.

## Architecture

| Module | Responsibility |
| --- | --- |
| `core/state.py` | `VehicleState`, `ControlInput` — frozen dataclasses |
| `core/engine.py` | torque curve, idle governor, friction, rev limiter |
| `core/gearbox.py` | ratios, shift validation, reverse rules |
| `core/chassis.py` | longitudinal integration, bicycle-model steering, thermal |
| `core/vehicle.py` | `Vehicle.step(state, control, dt)` — pure |
| `core/clock.py` | fixed-timestep accumulator, real-time and fast modes |
| `input/providers.py` | `InputProvider` protocol, `ScriptedInputProvider`, pedal ramping |
| `input/keyboard.py` | `KeyboardInputProvider` — pygame |
| `telemetry/mapper.py` | `VehicleState` → `TelemetryFrame` |
| `telemetry/sinks.py` | `JsonlSink`, `MemorySink`, `NullSink` |
| `session.py` | steps physics, samples telemetry, owns recording |
| `source.py` | `SimulatorTelemetrySource` — implements the shared protocol |
| `render/` | pygame scene and HUD — **the only pygame code besides input** |

**Pygame is isolated from the physics.** `drivesense_sim.core` and the whole
telemetry path import no pygame, and `tests/test_headless_purity.py` enforces
that in a subprocess rather than trusting convention.

### Three independent rates

| Stage | Rate | Why |
| --- | --- | --- |
| Physics | 120 Hz, fixed | Determinism. Variable-dt physics is not reproducible and no dynamics test would hold. |
| Rendering | ~60 FPS | Follows the display. |
| Telemetry | 10 Hz | What a real logger would use. |

### The `InputProvider` seam

`KeyboardInputProvider` and `ScriptedInputProvider` are interchangeable. The
physics, mapper and sinks are identical either way, which is what makes
headless dataset generation in Milestone 7 possible without restructuring
anything — profile drivers (calm / normal / aggressive) become new entries in
`drives.py` and nothing else changes.

## Recording

JSONL, one `TelemetryFrame` per line, plus a `.meta.json` sidecar holding the
vehicle spec, sim config, sample rate, generator version and git SHA. Without
the sidecar a recording cannot be reproduced later. Output goes to
`data/recordings/` and is gitignored.

## The physics model, honestly

This is a **simplified, physics-inspired model**, not validated vehicle
dynamics, and it does not reproduce any specific real vehicle.

What it does model: a piecewise-linear torque curve, an idle governor, engine
friction, a rev limiter with hysteresis, gear ratios with reflected engine
inertia, a rigid driveline when the clutch is engaged and free engine dynamics
when it is not, aerodynamic drag, rolling resistance, brake force, a kinematic
bicycle model capped at a tyre grip limit, and first-order coolant warm-up.

What it does not model: tyre slip, suspension, weight transfer, road gradient
or surface, differential behaviour, or torque converter effects.

The practical consequence is that simulator telemetry is **smoother than real
vehicle data** — less jerk, no sensor dropout, no road-surface noise. That is
why DriveSense commits to validating its models against real public telemetry
rather than relying on simulator data alone.

Two behaviours worth knowing:

- **Idle creep.** Below idle RPM in gear, the model floors engine speed at idle
  rather than lugging, which behaves like a slipping clutch. This is why
  stalling is opt-in.
- **Stalling** (`--stall`) is judged by the RPM the wheels *demand*, so
  releasing the clutch in gear at a standstill kills the engine, as it would in
  a real car. Restart by pressing the clutch or selecting neutral.

## Tests

```bash
pytest -q          # 96 tests, all headless (SDL dummy driver for render tests)
```

Coverage includes the torque curve and limiter, shift validation, force
integration, and behavioural assertions: upshift/downshift RPM changes match
the ratio quotient, RPM never exceeds the redline, braking reaches exactly
zero, speed never jumps between steps, and invariants hold under 60 s of
randomised input.

`test_golden_run.py` asserts both that a scripted drive is **bit-exact
repeatable** and that its summary still matches the committed fixture. If the
physics changes, it fails. Review why, then regenerate deliberately:

```bash
python -c "from tests.golden import write_fixture; write_fixture()"
```
