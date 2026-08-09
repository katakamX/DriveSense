"""Immutable state and control types.

Both are frozen: `Vehicle.step` is a pure function of (state, control, dt),
which is what makes every dynamics test a plain function call with no setup.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace

from drivesense_contracts import NEUTRAL_GEAR


@dataclass(frozen=True, slots=True)
class ControlInput:
    """Driver inputs for one physics step.

    Pedals are continuous 0..1. Gear changes are *edge events*: they are true
    for exactly one step, otherwise holding a key would walk through every
    gear in the box.
    """

    throttle: float = 0.0
    brake: float = 0.0
    clutch: float = 0.0
    steer: float = 0.0
    shift_up: bool = False
    shift_down: bool = False
    engage_reverse: bool = False
    engage_neutral: bool = False

    def without_edges(self) -> ControlInput:
        """Same inputs with all one-shot events cleared."""
        return replace(
            self,
            shift_up=False,
            shift_down=False,
            engage_reverse=False,
            engage_neutral=False,
        )


@dataclass(frozen=True, slots=True)
class VehicleState:
    """Complete physical state of the simulated vehicle."""

    sim_t: float = 0.0

    speed_mps: float = 0.0
    accel_ms2: float = 0.0
    engine_omega: float = 0.0  # rad/s

    throttle: float = 0.0
    brake: float = 0.0
    clutch: float = 0.0  # 1.0 = pedal fully down = fully disengaged
    gear: int = NEUTRAL_GEAR

    engine_torque_nm: float = 0.0
    engine_load: float = 0.0  # 0..1
    engine_on: bool = True
    rev_limiter_active: bool = False
    stalled: bool = False

    steering_deg: float = 0.0
    yaw_rate: float = 0.0  # rad/s
    lateral_accel_ms2: float = 0.0
    heading: float = 0.0  # rad
    pos_x: float = 0.0  # metres east
    pos_y: float = 0.0  # metres north

    distance_m: float = 0.0
    coolant_c: float = 25.0

    @property
    def engine_rpm(self) -> float:
        return self.engine_omega * 60.0 / (2.0 * math.pi)

    @property
    def speed_kph(self) -> float:
        return self.speed_mps * 3.6

    @property
    def clutch_engagement(self) -> float:
        """1.0 when the clutch is fully engaged (pedal released)."""
        return 1.0 - self.clutch


def rpm_to_omega(rpm: float) -> float:
    return rpm * 2.0 * math.pi / 60.0


def omega_to_rpm(omega: float) -> float:
    return omega * 60.0 / (2.0 * math.pi)
