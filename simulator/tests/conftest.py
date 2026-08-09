from __future__ import annotations

import pytest

from drivesense_sim.config import SimConfig, VehicleSpec
from drivesense_sim.core.vehicle import Vehicle
from drivesense_sim.input.providers import ScriptedInputProvider, ScriptStep
from drivesense_sim.session import SimulationSession


@pytest.fixture(scope="session")
def spec() -> VehicleSpec:
    return VehicleSpec.load()


@pytest.fixture
def config() -> SimConfig:
    return SimConfig()


@pytest.fixture
def vehicle(spec: VehicleSpec, config: SimConfig) -> Vehicle:
    return Vehicle(spec, config)


def make_session(
    steps: list[ScriptStep],
    spec: VehicleSpec,
    config: SimConfig,
    *,
    smooth: bool = False,
) -> SimulationSession:
    """Session driven by a scripted driver. Unsmoothed by default so tests
    assert on the inputs they actually specify."""
    return SimulationSession(ScriptedInputProvider(steps, config, smooth=smooth), spec, config)
