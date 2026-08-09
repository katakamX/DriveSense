"""Simulation session: physics stepping plus telemetry sampling.

Shared by the interactive pygame application and the headless telemetry
source, so both drive exactly the same model through exactly the same path.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from pathlib import Path

from drivesense_contracts import TelemetryFrame, TelemetrySink, TripMeta
from drivesense_sim import __version__
from drivesense_sim.config import SimConfig, VehicleSpec
from drivesense_sim.core.state import ControlInput, VehicleState
from drivesense_sim.core.vehicle import Vehicle
from drivesense_sim.input.providers import InputProvider
from drivesense_sim.telemetry.mapper import TelemetryMapper

GENERATOR = "drivesense-sim"


def read_git_sha(start: Path | None = None) -> str | None:
    """Best-effort git SHA without shelling out. Returns None if unavailable."""
    directory = (start or Path(__file__)).resolve()
    for candidate in [directory, *directory.parents]:
        git_dir = candidate / ".git"
        if not git_dir.is_dir():
            continue
        try:
            head = (git_dir / "HEAD").read_text(encoding="utf-8").strip()
            if head.startswith("ref:"):
                ref = git_dir / head.removeprefix("ref:").strip()
                return ref.read_text(encoding="utf-8").strip() if ref.exists() else None
            return head
        except OSError:
            return None
    return None


class SimulationSession:
    """Advances the vehicle and emits telemetry at the configured rate."""

    def __init__(
        self,
        provider: InputProvider,
        spec: VehicleSpec | None = None,
        config: SimConfig | None = None,
        *,
        trip_id: str | None = None,
        started_at: datetime | None = None,
    ) -> None:
        self.config = config or SimConfig()
        self.spec = spec or VehicleSpec.load()
        self.provider = provider
        self.vehicle = Vehicle(self.spec, self.config)
        self.state: VehicleState = self.vehicle.initial_state()
        self.trip_id = trip_id or f"sim-{uuid.uuid4().hex[:12]}"
        self.started_at = started_at or datetime.now(UTC)

        self._mapper = TelemetryMapper(self.config, self.trip_id, self.started_at)
        self._sink: TelemetrySink | None = None
        self._step_index = 0
        self.frames_emitted = 0
        self.last_frame: TelemetryFrame | None = None

        # Telemetry is sampled every N physics steps rather than by comparing
        # floats, which keeps sampling exactly reproducible.
        self._steps_per_sample = max(1, round(self.config.physics_hz / self.config.telemetry_hz))

    # --- Recording ----------------------------------------------------------

    @property
    def recording(self) -> bool:
        return self._sink is not None

    def build_meta(self) -> TripMeta:
        return TripMeta(
            trip_id=self.trip_id,
            source="simulator",
            started_at=self.started_at,
            sample_rate_hz=self.config.telemetry_hz,
            generator=GENERATOR,
            generator_version=__version__,
            git_sha=read_git_sha(),
            vehicle=self.spec.model_dump(mode="json"),
            config=self.config.model_dump(mode="json"),
        )

    def attach_sink(self, sink: TelemetrySink) -> None:
        sink.open(self.build_meta())
        self._sink = sink

    def detach_sink(self) -> None:
        if self._sink is not None:
            self._sink.close()
            self._sink = None

    # --- Stepping -----------------------------------------------------------

    def step_once(self) -> TelemetryFrame | None:
        """Advance exactly one fixed physics step; sample telemetry if due."""
        dt = self.config.physics_dt
        control: ControlInput = self.provider.poll(self.state, dt)
        self.state = self.vehicle.step(self.state, control, dt)

        frame: TelemetryFrame | None = None
        if self._step_index % self._steps_per_sample == 0:
            frame = self._mapper.to_frame(self.state)
            self.last_frame = frame
            self.frames_emitted += 1
            if self._sink is not None:
                self._sink.write(frame)

        self._step_index += 1
        return frame

    def advance_steps(self, steps: int) -> list[TelemetryFrame]:
        frames: list[TelemetryFrame] = []
        for _ in range(steps):
            frame = self.step_once()
            if frame is not None:
                frames.append(frame)
        return frames

    def advance_seconds(self, duration_s: float) -> list[TelemetryFrame]:
        return self.advance_steps(int(round(duration_s / self.config.physics_dt)))

    def close(self) -> None:
        self.detach_sink()
