"""Behavioural tests for the whole vehicle — the requirements from the brief,
asserted numerically rather than eyeballed in the window."""

from __future__ import annotations

import random

import pytest

from drivesense_contracts import NEUTRAL_GEAR, REVERSE_GEAR
from drivesense_sim.config import SimConfig, VehicleSpec
from drivesense_sim.core.state import ControlInput
from drivesense_sim.core.vehicle import Vehicle
from drivesense_sim.input.providers import ScriptStep
from tests.conftest import make_session

DT = 1 / 120


def run(vehicle: Vehicle, control: ControlInput, seconds: float, state=None):  # type: ignore[no-untyped-def]
    state = state if state is not None else vehicle.initial_state()
    for _ in range(int(seconds / DT)):
        state = vehicle.step(state, control, DT)
        control = control.without_edges()
    return state


def test_engine_idles_when_untouched(vehicle: Vehicle, spec: VehicleSpec) -> None:
    state = run(vehicle, ControlInput(), 5.0)

    assert state.engine_rpm == pytest.approx(spec.idle_rpm, abs=30.0)
    assert state.speed_mps == 0.0


def test_throttle_in_neutral_revs_the_engine_without_moving(
    vehicle: Vehicle, spec: VehicleSpec
) -> None:
    state = run(vehicle, ControlInput(throttle=1.0), 3.0)

    assert state.gear == NEUTRAL_GEAR
    assert state.engine_rpm > spec.idle_rpm * 3
    assert state.speed_mps == pytest.approx(0.0, abs=1e-9)


def test_throttle_in_gear_accelerates(vehicle: Vehicle) -> None:
    state = run(vehicle, ControlInput(shift_up=True), 0.1)
    state = run(vehicle, ControlInput(throttle=1.0), 4.0, state)

    assert state.gear == 1
    assert state.speed_kph > 20.0
    assert state.distance_m > 0.0


def test_speed_never_jumps_between_steps(vehicle: Vehicle) -> None:
    """Force-based integration bounds the change in speed per step."""
    rng = random.Random(7)
    state = vehicle.initial_state()
    max_delta = 0.0

    for _ in range(120 * 40):
        control = ControlInput(
            throttle=rng.random(),
            brake=rng.random(),
            clutch=rng.random() * 0.4,
            steer=rng.uniform(-1.0, 1.0),
            shift_up=rng.random() < 0.01,
            shift_down=rng.random() < 0.01,
        )
        previous = state.speed_mps
        state = vehicle.step(state, control, DT)
        max_delta = max(max_delta, abs(state.speed_mps - previous))

    # 1 g in a single 1/120 s step would be 0.08 m/s; anything beyond that is
    # a discontinuity, not acceleration.
    assert max_delta < 0.15


def test_upshifting_lowers_rpm_by_the_ratio_quotient(vehicle: Vehicle, spec: VehicleSpec) -> None:
    state = run(vehicle, ControlInput(shift_up=True), 0.1)
    state = run(vehicle, ControlInput(throttle=1.0), 6.0, state)

    before = state.engine_rpm
    state = vehicle.step(state, ControlInput(throttle=0.0, shift_up=True), DT)
    after = state.engine_rpm

    assert state.gear == 2
    expected = before * (spec.gear_ratios[1] / spec.gear_ratios[0])
    assert after == pytest.approx(expected, rel=0.02)
    assert after < before


def test_downshifting_raises_rpm(vehicle: Vehicle, spec: VehicleSpec) -> None:
    state = run(vehicle, ControlInput(shift_up=True), 0.1)
    state = run(vehicle, ControlInput(throttle=1.0), 6.0, state)
    state = run(vehicle, ControlInput(throttle=0.6, shift_up=True), 5.0, state)
    assert state.gear == 2

    before = state.engine_rpm
    state = vehicle.step(state, ControlInput(shift_down=True), DT)

    assert state.gear == 1
    expected = before * (spec.gear_ratios[0] / spec.gear_ratios[1])
    assert state.engine_rpm == pytest.approx(expected, rel=0.02)
    assert state.engine_rpm > before


def test_rpm_never_exceeds_the_redline(vehicle: Vehicle, spec: VehicleSpec) -> None:
    state = run(vehicle, ControlInput(shift_up=True), 0.1)
    state = run(vehicle, ControlInput(throttle=1.0), 40.0, state)

    assert state.engine_rpm <= spec.redline_rpm * 1.02
    assert state.rev_limiter_active or state.engine_rpm < spec.redline_rpm


def test_neutral_revving_hits_the_limiter_at_zero_speed(
    vehicle: Vehicle, spec: VehicleSpec
) -> None:
    state = run(vehicle, ControlInput(throttle=1.0), 8.0)

    assert state.rev_limiter_active is True
    assert state.engine_rpm <= spec.redline_rpm * 1.02
    assert state.speed_mps == pytest.approx(0.0, abs=1e-9)


def test_braking_brings_the_vehicle_to_a_complete_stop(vehicle: Vehicle) -> None:
    state = run(vehicle, ControlInput(shift_up=True), 0.1)
    state = run(vehicle, ControlInput(throttle=1.0), 6.0, state)
    assert state.speed_kph > 20.0

    state = run(vehicle, ControlInput(brake=1.0, clutch=1.0), 8.0, state)

    assert state.speed_mps == 0.0


def test_engine_braking_does_not_drag_the_car_backwards(vehicle: Vehicle) -> None:
    state = run(vehicle, ControlInput(shift_up=True), 0.1)
    state = run(vehicle, ControlInput(), 5.0, state)

    assert state.speed_mps >= 0.0


def test_coasting_decelerates(vehicle: Vehicle) -> None:
    state = run(vehicle, ControlInput(shift_up=True), 0.1)
    state = run(vehicle, ControlInput(throttle=1.0), 6.0, state)

    before = state.speed_mps
    state = run(vehicle, ControlInput(clutch=1.0), 4.0, state)

    assert state.speed_mps < before


def test_lower_gears_accelerate_harder(vehicle: Vehicle) -> None:
    first = run(vehicle, ControlInput(shift_up=True), 0.1)
    first = run(vehicle, ControlInput(throttle=1.0), 2.0, first)

    third = run(vehicle, ControlInput(shift_up=True), 0.1)
    third = run(vehicle, ControlInput(shift_up=True), 0.1, third)
    third = run(vehicle, ControlInput(shift_up=True), 0.1, third)
    third = run(vehicle, ControlInput(throttle=1.0), 2.0, third)

    assert first.speed_mps > third.speed_mps


def test_reverse_moves_the_vehicle_backwards(vehicle: Vehicle) -> None:
    state = run(vehicle, ControlInput(engage_reverse=True), 0.1)
    assert state.gear == REVERSE_GEAR

    state = run(vehicle, ControlInput(throttle=0.6), 3.0, state)

    assert state.speed_mps < -0.5


def test_steering_produces_yaw_and_lateral_acceleration(vehicle: Vehicle) -> None:
    state = run(vehicle, ControlInput(shift_up=True), 0.1)
    state = run(vehicle, ControlInput(throttle=1.0), 6.0, state)
    state = run(vehicle, ControlInput(throttle=0.4, steer=1.0), 2.0, state)

    assert state.steering_deg > 0.0
    assert state.yaw_rate > 0.0
    assert abs(state.lateral_accel_ms2) > 0.1
    assert state.heading != 0.0


def test_invariants_hold_under_random_input(vehicle: Vehicle, spec: VehicleSpec) -> None:
    rng = random.Random(1234)
    state = vehicle.initial_state()

    for _ in range(120 * 60):
        state = vehicle.step(
            state,
            ControlInput(
                throttle=rng.random(),
                brake=rng.random(),
                clutch=rng.random(),
                steer=rng.uniform(-1.0, 1.0),
                shift_up=rng.random() < 0.02,
                shift_down=rng.random() < 0.02,
                engage_reverse=rng.random() < 0.002,
            ),
            DT,
        )
        assert 0.0 <= state.engine_rpm <= spec.redline_rpm * 1.05
        assert -60.0 < state.speed_kph < 400.0
        assert 0.0 <= state.engine_load <= 1.0
        assert abs(state.steering_deg) <= spec.max_steering_deg + 1e-6
        assert state.distance_m >= 0.0
        assert state.speed_mps == state.speed_mps  # not NaN


def test_stalling_is_disabled_by_default(spec: VehicleSpec) -> None:
    session = make_session(
        [ScriptStep(0.1, shift_up=True), ScriptStep(4.0, shift_up=True)], spec, SimConfig()
    )
    session.advance_seconds(4.1)

    assert session.state.stalled is False
    assert session.state.engine_on is True


def test_stalling_can_be_enabled(spec: VehicleSpec) -> None:
    config = SimConfig(stall_enabled=True)
    session = make_session(
        [ScriptStep(0.1, shift_up=True), ScriptStep(0.1, shift_up=True), ScriptStep(3.0)],
        spec,
        config,
    )
    session.advance_seconds(3.2)

    # Third gear at a standstill with the clutch out: the engine dies.
    assert session.state.stalled is True
    assert session.state.engine_on is False


def test_stalled_engine_restarts_with_the_clutch_down(spec: VehicleSpec) -> None:
    config = SimConfig(stall_enabled=True)
    session = make_session(
        [
            ScriptStep(0.1, shift_up=True),
            ScriptStep(0.1, shift_up=True),
            ScriptStep(2.0),
            ScriptStep(2.0, clutch=1.0),
        ],
        spec,
        config,
    )
    session.advance_seconds(4.2)

    assert session.state.stalled is False
    assert session.state.engine_on is True
