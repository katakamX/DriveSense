from __future__ import annotations

import pytest

from drivesense_contracts import NEUTRAL_GEAR, REVERSE_GEAR
from drivesense_sim.config import VehicleSpec
from drivesense_sim.core.gearbox import REVERSE_MAX_SPEED_MPS, Gearbox
from drivesense_sim.core.state import ControlInput


@pytest.fixture
def gearbox(spec: VehicleSpec) -> Gearbox:
    return Gearbox(spec)


def test_neutral_transmits_nothing(gearbox: Gearbox) -> None:
    assert gearbox.ratio(NEUTRAL_GEAR) == 0.0
    assert gearbox.direction(NEUTRAL_GEAR) == 0.0


def test_ratios_decrease_with_gear(gearbox: Gearbox, spec: VehicleSpec) -> None:
    ratios = [gearbox.ratio(gear) for gear in range(1, spec.max_forward_gear + 1)]

    assert ratios == sorted(ratios, reverse=True)


def test_direction_signs(gearbox: Gearbox) -> None:
    assert gearbox.direction(1) == 1.0
    assert gearbox.direction(REVERSE_GEAR) == -1.0


def test_upshift_walks_up_and_stops_at_top(gearbox: Gearbox, spec: VehicleSpec) -> None:
    gear = NEUTRAL_GEAR
    for expected in range(1, spec.max_forward_gear + 1):
        gear = gearbox.select(gear, ControlInput(shift_up=True), 10.0)
        assert gear == expected

    assert gearbox.select(gear, ControlInput(shift_up=True), 10.0) == spec.max_forward_gear


def test_downshift_walks_down_to_neutral(gearbox: Gearbox) -> None:
    gear = 3
    assert (gear := gearbox.select(gear, ControlInput(shift_down=True), 10.0)) == 2
    assert (gear := gearbox.select(gear, ControlInput(shift_down=True), 10.0)) == 1
    assert gearbox.select(gear, ControlInput(shift_down=True), 10.0) == NEUTRAL_GEAR


def test_no_shift_without_a_request(gearbox: Gearbox) -> None:
    assert gearbox.select(3, ControlInput(), 10.0) == 3


def test_reverse_is_refused_above_walking_pace(gearbox: Gearbox) -> None:
    assert gearbox.select(NEUTRAL_GEAR, ControlInput(engage_reverse=True), 12.0) == NEUTRAL_GEAR
    assert (
        gearbox.select(NEUTRAL_GEAR, ControlInput(engage_reverse=True), REVERSE_MAX_SPEED_MPS / 2)
        == REVERSE_GEAR
    )


def test_reverse_key_toggles_back_to_neutral(gearbox: Gearbox) -> None:
    assert gearbox.select(REVERSE_GEAR, ControlInput(engage_reverse=True), 0.0) == NEUTRAL_GEAR


def test_upshift_from_reverse_goes_to_neutral(gearbox: Gearbox) -> None:
    assert gearbox.select(REVERSE_GEAR, ControlInput(shift_up=True), 0.0) == NEUTRAL_GEAR


def test_neutral_request_always_wins(gearbox: Gearbox) -> None:
    assert gearbox.select(4, ControlInput(engage_neutral=True), 25.0) == NEUTRAL_GEAR
