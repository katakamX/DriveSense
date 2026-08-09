# simulator/ — Telemetry generator (Milestone 2)

Generates realistic vehicle telemetry from a simple physics model with
parameterised driver profiles (calm, normal, aggressive, drowsy) across
scenarios (city, highway, mixed).

The simulator is a **client of the backend**, not part of it. It speaks the same
wire protocol the OBD2 source will speak in Milestone 13, which is what makes
the telemetry-source abstraction real rather than decorative: swapping in
hardware must not change a line of backend code.

To keep models from overfitting to unrealistically clean input, generated
telemetry includes sensor noise, dropped frames, GPS jitter and unsupported
PIDs.
