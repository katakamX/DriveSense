from __future__ import annotations

import pytest

from drivesense_sim.config import VehicleSpec
from drivesense_sim.core.engine import Engine, interpolate_curve
from drivesense_sim.core.state import rpm_to_omega

CURVE = [(1000.0, 100.0), (2000.0, 200.0), (3000.0, 150.0)]


@pytest.mark.parametrize(
    ("rpm", "expected"),
    [
        (500.0, 100.0),  # clamped below the first point
        (1000.0, 100.0),
        (1500.0, 150.0),  # linear interpolation
        (2000.0, 200.0),
        (2500.0, 175.0),
        (5000.0, 150.0),  # clamped above the last point
    ],
)
def test_curve_interpolation_is_piecewise_linear_and_clamped(rpm: float, expected: float) -> None:
    assert interpolate_curve(CURVE, rpm) == pytest.approx(expected)


def test_torque_scales_with_throttle(spec: VehicleSpec) -> None:
    engine = Engine(spec)
    full = engine.evaluate(3000.0, 1.0, limiter_was_active=False, running=True)
    half = engine.evaluate(3000.0, 0.5, limiter_was_active=False, running=True)

    assert half.torque_nm == pytest.approx(full.torque_nm * 0.5)
    assert full.load == pytest.approx(1.0)
    assert half.load == pytest.approx(0.5)


def test_torque_is_cut_at_the_redline(spec: VehicleSpec) -> None:
    engine = Engine(spec)
    output = engine.evaluate(spec.redline_rpm + 1.0, 1.0, limiter_was_active=False, running=True)

    assert output.limiter_active is True
    assert output.torque_nm == 0.0


def test_limiter_hysteresis_holds_until_rpm_falls(spec: VehicleSpec) -> None:
    engine = Engine(spec)
    just_below = spec.redline_rpm - spec.limiter_hysteresis_rpm / 2

    still_cutting = engine.evaluate(just_below, 1.0, limiter_was_active=True, running=True)
    recovered = engine.evaluate(
        spec.redline_rpm - spec.limiter_hysteresis_rpm - 1.0,
        1.0,
        limiter_was_active=True,
        running=True,
    )

    assert still_cutting.limiter_active is True
    assert recovered.limiter_active is False


def test_idle_governor_supplies_torque_below_idle(spec: VehicleSpec) -> None:
    engine = Engine(spec)
    output = engine.evaluate(spec.idle_rpm * 0.5, 0.0, limiter_was_active=False, running=True)

    assert output.torque_nm > 0.0


def test_no_governor_torque_above_idle_off_throttle(spec: VehicleSpec) -> None:
    engine = Engine(spec)
    output = engine.evaluate(spec.idle_rpm + 500.0, 0.0, limiter_was_active=False, running=True)

    assert output.torque_nm == 0.0


def test_stopped_engine_produces_nothing(spec: VehicleSpec) -> None:
    engine = Engine(spec)
    output = engine.evaluate(0.0, 1.0, limiter_was_active=False, running=False)

    assert output.torque_nm == 0.0
    assert output.load == 0.0


def test_friction_rises_with_speed(spec: VehicleSpec) -> None:
    engine = Engine(spec)

    assert engine.friction_torque(rpm_to_omega(5000.0)) > engine.friction_torque(
        rpm_to_omega(1000.0)
    )
