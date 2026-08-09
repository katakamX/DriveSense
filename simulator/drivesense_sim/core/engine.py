"""Engine torque production.

A piecewise-linear wide-open-throttle torque curve scaled by throttle, plus an
idle governor, internal friction, and a rev limiter with hysteresis. Torque is
produced here; what the driveline does with it belongs to gearbox/chassis.
"""

from __future__ import annotations

from dataclasses import dataclass

from drivesense_sim.config import VehicleSpec
from drivesense_sim.core.state import rpm_to_omega

# Width of the proportional band below idle, as a fraction of idle RPM.
IDLE_BAND_FRACTION = 0.15


def interpolate_curve(curve: list[tuple[float, float]], x: float) -> float:
    """Piecewise-linear lookup, clamped at both ends."""
    if x <= curve[0][0]:
        return curve[0][1]
    if x >= curve[-1][0]:
        return curve[-1][1]
    for (x0, y0), (x1, y1) in zip(curve, curve[1:], strict=False):
        if x0 <= x <= x1:
            span = x1 - x0
            if span <= 0.0:
                return y1
            return y0 + (y1 - y0) * (x - x0) / span
    return curve[-1][1]


@dataclass(frozen=True, slots=True)
class EngineOutput:
    torque_nm: float
    """Net torque at the flywheel, after friction and the idle governor."""

    gross_torque_nm: float
    """Combustion torque only — the numerator of engine load."""

    load: float
    """0..1, actual torque divided by what is available at this RPM."""

    limiter_active: bool


class Engine:
    def __init__(self, spec: VehicleSpec) -> None:
        self._spec = spec

    def max_torque(self, rpm: float) -> float:
        return interpolate_curve(self._spec.torque_curve, rpm)

    def friction_torque(self, omega: float) -> float:
        spec = self._spec
        return spec.engine_friction_nm + spec.engine_friction_nm_per_rad_s * abs(omega)

    def evaluate(
        self,
        rpm: float,
        throttle: float,
        *,
        limiter_was_active: bool,
        running: bool,
    ) -> EngineOutput:
        spec = self._spec
        if not running:
            return EngineOutput(0.0, 0.0, 0.0, False)

        # Rev limiter: cut fuel at the redline, restore only after RPM has
        # fallen by the hysteresis band, which produces the characteristic
        # bounce instead of a numerical oscillation every step.
        if limiter_was_active:
            limiter_active = rpm > spec.redline_rpm - spec.limiter_hysteresis_rpm
        else:
            limiter_active = rpm >= spec.redline_rpm

        available = self.max_torque(rpm)
        gross = 0.0 if limiter_active else available * throttle

        # Idle governor: cancels internal friction and adds a proportional
        # correction, so the engine settles *at* idle rather than wherever a
        # fixed torque happens to balance friction.
        if rpm < spec.idle_rpm and not limiter_active:
            hold = self.friction_torque(rpm_to_omega(rpm))
            correction = spec.idle_governor_max_nm * min(
                1.0, (spec.idle_rpm - rpm) / (IDLE_BAND_FRACTION * spec.idle_rpm)
            )
            gross = max(gross, min(spec.idle_governor_max_nm, hold + correction))

        load = 0.0 if available <= 0.0 else max(0.0, min(1.0, gross / available))
        return EngineOutput(
            torque_nm=gross,
            gross_torque_nm=gross,
            load=load,
            limiter_active=limiter_active,
        )
