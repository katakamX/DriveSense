"""The vehicle model: engine + gearbox + chassis, stepped at a fixed timestep.

`Vehicle.step` is a pure function of (state, control, dt). It imports nothing
from pygame and performs no I/O, so the entire model is testable headlessly —
`tests/test_headless_purity.py` enforces that mechanically.

This is a simplified, physics-*inspired* model. It is not a validated vehicle
dynamics model and makes no claim to reproduce a specific real vehicle.
"""

from __future__ import annotations

import math
from dataclasses import replace

from drivesense_contracts import NEUTRAL_GEAR
from drivesense_sim.config import SimConfig, VehicleSpec
from drivesense_sim.core.chassis import STATIONARY_EPS, Chassis
from drivesense_sim.core.engine import Engine
from drivesense_sim.core.gearbox import Gearbox
from drivesense_sim.core.state import ControlInput, VehicleState, omega_to_rpm, rpm_to_omega

# Below this engagement the clutch transmits nothing and the engine spins free.
COUPLING_THRESHOLD = 0.05


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


class Vehicle:
    def __init__(self, spec: VehicleSpec, config: SimConfig | None = None) -> None:
        self.spec = spec
        self.config = config or SimConfig()
        self.engine = Engine(spec)
        self.gearbox = Gearbox(spec)
        self.chassis = Chassis(spec)

    def initial_state(self) -> VehicleState:
        return VehicleState(
            engine_omega=rpm_to_omega(self.spec.idle_rpm),
            coolant_c=self.spec.coolant_ambient_c,
        )

    def step(self, state: VehicleState, control: ControlInput, dt: float) -> VehicleState:
        spec = self.spec
        throttle = _clamp01(control.throttle)
        brake = _clamp01(control.brake)
        clutch = _clamp01(control.clutch)
        steer = max(-1.0, min(1.0, control.steer))

        gear = self.gearbox.select(state.gear, control, state.speed_mps)
        engagement = 1.0 - clutch

        engine_on, stalled = self._engine_power_state(state, clutch, gear)

        engine_out = self.engine.evaluate(
            state.engine_rpm,
            throttle,
            limiter_was_active=state.rev_limiter_active,
            running=engine_on,
        )
        friction = self.engine.friction_torque(state.engine_omega) if engine_on else 0.0
        net_engine_torque = engine_out.torque_nm - friction

        coupled = gear != NEUTRAL_GEAR and engagement > COUPLING_THRESHOLD

        # Free-spinning engine dynamics, used directly in neutral and blended
        # in while the clutch is slipping.
        free_omega = max(
            0.0, state.engine_omega + (net_engine_torque / spec.engine_inertia_kgm2) * dt
        )

        if coupled:
            total_ratio = self.gearbox.total_ratio(gear)
            direction = self.gearbox.direction(gear)
            drive_force = (
                net_engine_torque
                * total_ratio
                * spec.drivetrain_efficiency
                / spec.wheel_radius_m
                * direction
                * engagement
            )
            # Engine braking can slow the vehicle but must never drag it
            # backwards out of a standstill.
            if abs(state.speed_mps) < STATIONARY_EPS and drive_force * direction < 0.0:
                drive_force = 0.0
            # Reflected engine inertia makes low gears feel heavier, which is
            # the physically correct reason first gear accelerates hard but
            # cannot reach high speed.
            effective_mass = (
                spec.mass_kg + spec.engine_inertia_kgm2 * (total_ratio / spec.wheel_radius_m) ** 2
            )
            # Rigid driveline: RPM is dictated by road speed and gearing. Every
            # shift RPM change falls out of this rather than being scripted.
            wheel_omega = abs(state.speed_mps) / spec.wheel_radius_m
            target_omega = wheel_omega * total_ratio
            idle_floor = rpm_to_omega(spec.idle_rpm) if engine_on else 0.0
            coupled_omega = max(target_omega, idle_floor)
            new_omega = engagement * coupled_omega + (1.0 - engagement) * free_omega
        else:
            drive_force = 0.0
            effective_mass = spec.mass_kg
            new_omega = free_omega

        new_speed = self.chassis.integrate_speed(
            state.speed_mps, drive_force, brake, dt, effective_mass
        )
        accel = (new_speed - state.speed_mps) / dt

        steering_deg = self.chassis.update_steering(state.steering_deg, steer, new_speed, dt)
        yaw_rate, lateral_accel = self.chassis.lateral(new_speed, steering_deg)
        heading = (state.heading + yaw_rate * dt) % (2.0 * math.pi)

        return replace(
            state,
            sim_t=state.sim_t + dt,
            speed_mps=new_speed,
            accel_ms2=accel,
            engine_omega=new_omega,
            throttle=throttle,
            brake=brake,
            clutch=clutch,
            gear=gear,
            engine_torque_nm=engine_out.torque_nm,
            engine_load=engine_out.load,
            engine_on=engine_on,
            rev_limiter_active=engine_out.limiter_active,
            stalled=stalled,
            steering_deg=steering_deg,
            yaw_rate=yaw_rate,
            lateral_accel_ms2=lateral_accel,
            heading=heading,
            pos_x=state.pos_x + new_speed * math.sin(heading) * dt,
            pos_y=state.pos_y + new_speed * math.cos(heading) * dt,
            distance_m=state.distance_m + abs(new_speed) * dt,
            coolant_c=self.chassis.update_coolant(state.coolant_c, engine_out.load, engine_on, dt),
        )

    def _engine_power_state(
        self, state: VehicleState, clutch: float, gear: int
    ) -> tuple[bool, bool]:
        """Resolve stalling and restarting.

        Stalling is realistic manual-transmission behaviour but is disabled by
        default (`SimConfig.stall_enabled`): it makes casual demonstration
        frustrating without improving the telemetry.
        """
        if not self.config.stall_enabled:
            return True, False

        if state.stalled:
            # Turning the key: the clutch must be down, or the box in neutral.
            restarted = clutch > 0.9 or gear == NEUTRAL_GEAR
            return restarted, not restarted

        coupled = gear != NEUTRAL_GEAR and (1.0 - clutch) > 0.5
        if coupled:
            # Judge stalling by the RPM the wheels *demand*, not the current
            # RPM: the latter is floored at idle by the coupling model and so
            # would never fall far enough to stall.
            demanded_rpm = omega_to_rpm(
                abs(state.speed_mps) / self.spec.wheel_radius_m * self.gearbox.total_ratio(gear)
            )
            if demanded_rpm < self.spec.stall_rpm:
                return False, True
        return True, False
