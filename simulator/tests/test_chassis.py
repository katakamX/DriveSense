from __future__ import annotations

import math

import pytest

from drivesense_sim.config import VehicleSpec
from drivesense_sim.core.chassis import Chassis


@pytest.fixture
def chassis(spec: VehicleSpec) -> Chassis:
    return Chassis(spec)


def test_drag_grows_with_the_square_of_speed(chassis: Chassis) -> None:
    assert chassis.drag_force(20.0) == pytest.approx(chassis.drag_force(10.0) * 4.0)


def test_rolling_resistance_vanishes_at_a_standstill(chassis: Chassis) -> None:
    assert chassis.rolling_force(0.0) == 0.0
    assert chassis.rolling_force(10.0) > 0.0


def test_resistance_alone_slows_a_coasting_vehicle(chassis: Chassis, spec: VehicleSpec) -> None:
    speed = chassis.integrate_speed(25.0, 0.0, 0.0, 0.01, spec.mass_kg)

    assert speed < 25.0


def test_braking_settles_at_zero_without_reversing(chassis: Chassis, spec: VehicleSpec) -> None:
    speed = 0.4
    for _ in range(200):
        speed = chassis.integrate_speed(speed, 0.0, 1.0, 1 / 120, spec.mass_kg)

    assert speed == 0.0


def test_brakes_cannot_push_a_stationary_vehicle(chassis: Chassis, spec: VehicleSpec) -> None:
    assert chassis.integrate_speed(0.0, 0.0, 1.0, 0.01, spec.mass_kg) == 0.0


def test_brakes_hold_against_drive_torque(chassis: Chassis, spec: VehicleSpec) -> None:
    drive = 500.0
    braking = spec.max_brake_force_n

    assert chassis.integrate_speed(0.0, drive, braking / drive, 0.01, spec.mass_kg) == 0.0


def test_steering_ramps_rather_than_snapping(chassis: Chassis, spec: VehicleSpec) -> None:
    angle = chassis.update_steering(0.0, 1.0, 0.0, 1 / 120)

    assert 0.0 < angle < spec.max_steering_deg


def test_steering_authority_falls_off_with_speed(chassis: Chassis) -> None:
    slow = 0.0
    fast = 0.0
    for _ in range(600):
        slow = chassis.update_steering(slow, 1.0, 1.0, 1 / 120)
        fast = chassis.update_steering(fast, 1.0, 40.0, 1 / 120)

    assert fast < slow


def test_steering_returns_to_centre_when_released(chassis: Chassis) -> None:
    angle = 20.0
    for _ in range(600):
        angle = chassis.update_steering(angle, 0.0, 10.0, 1 / 120)

    assert angle == pytest.approx(0.0, abs=1e-6)


def test_yaw_rate_is_zero_when_stationary_or_straight(chassis: Chassis) -> None:
    assert chassis.lateral(0.0, 20.0) == (0.0, 0.0)
    assert chassis.lateral(20.0, 0.0) == (0.0, 0.0)


def test_lateral_acceleration_follows_the_bicycle_model_below_the_grip_limit(
    chassis: Chassis, spec: VehicleSpec
) -> None:
    speed, steer = 8.0, 6.0
    yaw_rate, lateral = chassis.lateral(speed, steer)

    expected_yaw = speed * math.tan(math.radians(steer)) / spec.wheelbase_m
    assert abs(lateral) < spec.max_lateral_accel_ms2
    assert yaw_rate == pytest.approx(expected_yaw)
    assert lateral == pytest.approx(speed * expected_yaw)


def test_lateral_acceleration_is_capped_by_tyre_grip(chassis: Chassis, spec: VehicleSpec) -> None:
    """Without this cap the geometric model reports well over 1 g, which would
    feed nonsense into harsh-cornering detection later."""
    speed, steer = 30.0, spec.max_steering_deg

    yaw_rate, lateral = chassis.lateral(speed, steer)

    assert abs(lateral) == pytest.approx(spec.max_lateral_accel_ms2)
    # Yaw rate is reduced to match the available grip: that is understeer.
    assert yaw_rate == pytest.approx(lateral / speed)
    assert yaw_rate < speed * math.tan(math.radians(steer)) / spec.wheelbase_m


def _soak(chassis: Chassis, start: float, load: float, *, running: bool = True) -> float:
    temp = start
    for _ in range(120 * 600):
        temp = chassis.update_coolant(temp, load, running, 1 / 120)
    return temp


def test_coolant_warms_toward_operating_temperature(chassis: Chassis, spec: VehicleSpec) -> None:
    assert _soak(chassis, spec.coolant_ambient_c, 1.0) == pytest.approx(
        spec.coolant_operating_c, abs=0.5
    )


def test_coolant_runs_hotter_under_higher_load(chassis: Chassis, spec: VehicleSpec) -> None:
    assert _soak(chassis, spec.coolant_ambient_c, 0.2) < _soak(chassis, spec.coolant_ambient_c, 1.0)


def test_coolant_cools_toward_ambient_when_the_engine_is_off(
    chassis: Chassis, spec: VehicleSpec
) -> None:
    assert _soak(chassis, spec.coolant_operating_c, 0.0, running=False) == pytest.approx(
        spec.coolant_ambient_c, abs=0.5
    )
