"""Longitudinal and lateral chassis dynamics.

Longitudinal motion is force-based and integrated at a fixed timestep, so the
vehicle can never jump between speeds. Lateral motion uses a kinematic bicycle
model, which is adequate for producing believable yaw rate and lateral
acceleration without pretending to model tyre slip.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from drivesense_sim.config import VehicleSpec

GRAVITY = 9.81
# Above this the vehicle is "moving" for the purposes of engine-braking rules.
STATIONARY_EPS = 0.05
# Below this the vehicle is at rest. Residual velocity smaller than this is
# snapped to zero so the car cannot creep indefinitely at an invisible speed.
CREEP_EPS = 1e-3


@dataclass(frozen=True, slots=True)
class LateralState:
    steering_deg: float
    yaw_rate: float
    lateral_accel: float


class Chassis:
    def __init__(self, spec: VehicleSpec) -> None:
        self._spec = spec

    # --- Longitudinal -------------------------------------------------------

    def drag_force(self, speed_mps: float) -> float:
        spec = self._spec
        return (
            0.5
            * spec.air_density
            * spec.drag_coefficient
            * spec.frontal_area_m2
            * speed_mps
            * speed_mps
        )

    def rolling_force(self, speed_mps: float) -> float:
        if abs(speed_mps) < CREEP_EPS:
            return 0.0
        return self._spec.rolling_resistance_coeff * self._spec.mass_kg * GRAVITY

    def brake_force(self, brake: float) -> float:
        return brake * self._spec.max_brake_force_n

    def integrate_speed(
        self, speed_mps: float, drive_force: float, brake: float, dt: float, effective_mass: float
    ) -> float:
        """Advance longitudinal speed by one step. Signed: negative is reverse."""
        resistance = self.drag_force(speed_mps) + self.rolling_force(speed_mps)
        braking = self.brake_force(brake)

        if abs(speed_mps) < CREEP_EPS:
            # At rest: resistive forces cannot push the vehicle, and the brakes
            # can only cancel drive torque, not reverse it.
            opposing = min(abs(drive_force), braking)
            net = drive_force - math.copysign(opposing, drive_force)
            new_speed = speed_mps + (net / effective_mass) * dt
            return 0.0 if abs(new_speed) < CREEP_EPS else new_speed

        direction = math.copysign(1.0, speed_mps)
        net = drive_force - direction * (resistance + braking)
        new_speed = speed_mps + (net / effective_mass) * dt

        # Settle at a standstill rather than oscillating around it: if the
        # only forces left are resistive, a zero crossing means "stopped".
        if new_speed * speed_mps < 0.0 and abs(drive_force) <= braking + resistance:
            return 0.0
        if abs(new_speed) < CREEP_EPS and abs(drive_force) <= braking + resistance:
            return 0.0
        return new_speed

    # --- Lateral ------------------------------------------------------------

    def update_steering(
        self, steering_deg: float, steer_input: float, speed_mps: float, dt: float
    ) -> float:
        spec = self._spec
        speed_kph = abs(speed_mps) * 3.6
        # Steering authority falls off with speed, as power steering and
        # stability would in a real car.
        authority = 1.0 / (1.0 + speed_kph / spec.steering_falloff_kph)
        target = steer_input * spec.max_steering_deg * authority

        rate = spec.steering_rate_dps if abs(steer_input) > 0.01 else spec.steering_return_dps
        max_step = rate * dt
        delta = max(-max_step, min(max_step, target - steering_deg))
        return steering_deg + delta

    def lateral(self, speed_mps: float, steering_deg: float) -> tuple[float, float]:
        """Return (yaw_rate rad/s, lateral acceleration m/s²).

        The bicycle model on its own is purely geometric and will happily
        report several g of cornering force at speed. Real tyres saturate, so
        lateral acceleration is capped at the grip limit and the yaw rate is
        reduced to match — which is what understeer is.
        """
        yaw_rate = speed_mps * math.tan(math.radians(steering_deg)) / self._spec.wheelbase_m
        lateral = speed_mps * yaw_rate

        limit = self._spec.max_lateral_accel_ms2
        if abs(lateral) > limit and abs(speed_mps) > STATIONARY_EPS:
            lateral = math.copysign(limit, lateral)
            yaw_rate = lateral / speed_mps
        return yaw_rate, lateral

    # --- Thermal ------------------------------------------------------------

    def update_coolant(self, coolant_c: float, load: float, running: bool, dt: float) -> float:
        spec = self._spec
        target = (
            spec.coolant_operating_c * (0.94 + 0.06 * load) if running else spec.coolant_ambient_c
        )
        return coolant_c + (target - coolant_c) * (dt / spec.coolant_time_constant_s)
