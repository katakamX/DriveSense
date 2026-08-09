"""Input providers — the seam that lets the same physics serve two purposes.

`InputProvider` is the only thing standing between a human at a keyboard and a
scripted driver. Physics, telemetry mapping and sinks are identical either
way, so headless dataset generation (Milestone 7) needs no restructuring:

    KeyboardInputProvider ─┐
                           ├─► Vehicle.step ─► TelemetryFrame ─► sink
    ScriptedInputProvider ─┘

This module must stay free of pygame; the keyboard provider lives next door.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from drivesense_sim.config import SimConfig
from drivesense_sim.core.state import ControlInput, VehicleState


class InputProvider(Protocol):
    def poll(self, state: VehicleState, dt: float) -> ControlInput:
        """Return the driver's inputs for the next physics step."""
        ...


def _approach(current: float, target: float, rate: float, dt: float) -> float:
    step = rate * dt
    if target > current:
        return min(target, current + step)
    return max(target, current - step)


class ControlSmoother:
    """Ramps pedal positions toward their targets.

    Keyboard input is binary. Feeding raw 0/1 pedals into the model produces
    square-wave telemetry, which is both unrealistic and degenerate for the
    feature engineering in later milestones.
    """

    def __init__(self, config: SimConfig) -> None:
        self._config = config
        self.throttle = 0.0
        self.brake = 0.0
        self.clutch = 0.0
        self.steer = 0.0

    def apply(self, target: ControlInput, dt: float) -> ControlInput:
        cfg = self._config
        self.throttle = _approach(self.throttle, target.throttle, cfg.throttle_rate_per_s, dt)
        self.brake = _approach(self.brake, target.brake, cfg.brake_rate_per_s, dt)
        self.clutch = _approach(self.clutch, target.clutch, cfg.clutch_rate_per_s, dt)
        self.steer = target.steer
        return ControlInput(
            throttle=self.throttle,
            brake=self.brake,
            clutch=self.clutch,
            steer=self.steer,
            shift_up=target.shift_up,
            shift_down=target.shift_down,
            engage_reverse=target.engage_reverse,
            engage_neutral=target.engage_neutral,
        )


@dataclass(frozen=True, slots=True)
class ScriptStep:
    """One segment of a scripted drive.

    Pedal values are held for `duration_s`; the shift flags fire once, on the
    step that enters this segment.
    """

    duration_s: float
    throttle: float = 0.0
    brake: float = 0.0
    clutch: float = 0.0
    steer: float = 0.0
    shift_up: bool = False
    shift_down: bool = False
    engage_reverse: bool = False
    engage_neutral: bool = False


@dataclass
class ScriptedInputProvider:
    """Deterministic driver used by golden tests and dataset generation."""

    steps: list[ScriptStep]
    config: SimConfig = field(default_factory=SimConfig)
    smooth: bool = True

    def __post_init__(self) -> None:
        self._elapsed = 0.0
        self._index = 0
        self._segment_started = False
        self._smoother = ControlSmoother(self.config)

    @property
    def finished(self) -> bool:
        return self._index >= len(self.steps)

    @property
    def total_duration(self) -> float:
        return sum(step.duration_s for step in self.steps)

    def poll(self, state: VehicleState, dt: float) -> ControlInput:
        if self.finished:
            return ControlInput()

        step = self.steps[self._index]
        first_tick = not self._segment_started
        self._segment_started = True

        target = ControlInput(
            throttle=step.throttle,
            brake=step.brake,
            clutch=step.clutch,
            steer=step.steer,
            shift_up=step.shift_up and first_tick,
            shift_down=step.shift_down and first_tick,
            engage_reverse=step.engage_reverse and first_tick,
            engage_neutral=step.engage_neutral and first_tick,
        )

        self._elapsed += dt
        if self._elapsed >= step.duration_s:
            self._elapsed = 0.0
            self._index += 1
            self._segment_started = False

        return self._smoother.apply(target, dt) if self.smooth else target
