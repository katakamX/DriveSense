"""Gear selection and ratios.

Shift requests are validated here so the physics model never sees an
impossible gear. Reverse is refused above walking pace, which is the one
protection a real synchromesh box gives you for free.
"""

from __future__ import annotations

from drivesense_contracts import NEUTRAL_GEAR, REVERSE_GEAR
from drivesense_sim.config import VehicleSpec
from drivesense_sim.core.state import ControlInput

REVERSE_MAX_SPEED_MPS = 1.5


class Gearbox:
    def __init__(self, spec: VehicleSpec) -> None:
        self._spec = spec

    def ratio(self, gear: int) -> float:
        """Gear ratio magnitude. Neutral transmits nothing."""
        spec = self._spec
        if gear == NEUTRAL_GEAR:
            return 0.0
        if gear == REVERSE_GEAR:
            return spec.reverse_ratio
        return spec.gear_ratios[gear - 1]

    def total_ratio(self, gear: int) -> float:
        return self.ratio(gear) * self._spec.final_drive

    @staticmethod
    def direction(gear: int) -> float:
        """+1 driving forward, -1 in reverse, 0 in neutral."""
        if gear == REVERSE_GEAR:
            return -1.0
        if gear == NEUTRAL_GEAR:
            return 0.0
        return 1.0

    def select(self, gear: int, control: ControlInput, speed_mps: float) -> int:
        """Apply a shift request, returning the resulting gear."""
        spec = self._spec

        if control.engage_neutral:
            return NEUTRAL_GEAR

        if control.engage_reverse:
            if abs(speed_mps) > REVERSE_MAX_SPEED_MPS:
                return gear
            return NEUTRAL_GEAR if gear == REVERSE_GEAR else REVERSE_GEAR

        if control.shift_up:
            if gear == REVERSE_GEAR:
                return NEUTRAL_GEAR
            if gear < spec.max_forward_gear:
                return gear + 1
            return gear

        if control.shift_down:
            if gear > 1:
                return gear - 1
            if gear == 1:
                return NEUTRAL_GEAR
            if gear == NEUTRAL_GEAR and abs(speed_mps) <= REVERSE_MAX_SPEED_MPS:
                return REVERSE_GEAR
            return gear

        return gear
