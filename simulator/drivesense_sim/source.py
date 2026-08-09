"""`SimulatorTelemetrySource` — the simulator as a producer-side source.

Implements the shared `TelemetrySource` protocol, so the future OBD2 adapter
is a drop-in alternative from the publisher's point of view. The backend never
sees this class; it receives frames over the network (ADR 0001, ADR 0005).

Runs headless and as fast as the CPU allows, which is what makes bulk dataset
generation practical in Milestone 7.
"""

from __future__ import annotations

from collections.abc import Iterator

from drivesense_contracts import TelemetryFrame, TripMeta
from drivesense_sim.config import SimConfig, VehicleSpec
from drivesense_sim.input.providers import ScriptedInputProvider
from drivesense_sim.session import SimulationSession


class SimulatorTelemetrySource:
    def __init__(
        self,
        provider: ScriptedInputProvider,
        spec: VehicleSpec | None = None,
        config: SimConfig | None = None,
        duration_s: float | None = None,
    ) -> None:
        self._provider = provider
        self._spec = spec
        self._config = config or SimConfig()
        self._duration_s = duration_s if duration_s is not None else provider.total_duration
        self._session: SimulationSession | None = None

    @property
    def source_name(self) -> str:
        return "simulator"

    @property
    def session(self) -> SimulationSession:
        if self._session is None:
            raise RuntimeError("SimulatorTelemetrySource.start() has not been called")
        return self._session

    def start(self, trip_id: str) -> TripMeta:
        self._session = SimulationSession(self._provider, self._spec, self._config, trip_id=trip_id)
        return self._session.build_meta()

    def frames(self) -> Iterator[TelemetryFrame]:
        session = self.session
        steps = int(round(self._duration_s / self._config.physics_dt))
        for _ in range(steps):
            frame = session.step_once()
            if frame is not None:
                yield frame

    def stop(self) -> None:
        if self._session is not None:
            self._session.close()
