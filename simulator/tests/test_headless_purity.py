"""The separation requirement, enforced mechanically rather than by convention.

If someone imports pygame into the physics model, this fails. A subprocess is
used because another test module in the same session may legitimately have
imported pygame already.
"""

from __future__ import annotations

import subprocess
import sys

CHECK = """
import sys
import drivesense_sim.core.vehicle          # noqa: F401
import drivesense_sim.core.engine           # noqa: F401
import drivesense_sim.core.gearbox          # noqa: F401
import drivesense_sim.core.chassis          # noqa: F401
import drivesense_sim.core.clock            # noqa: F401
import drivesense_sim.session               # noqa: F401
import drivesense_sim.source                # noqa: F401
import drivesense_sim.telemetry.mapper      # noqa: F401
import drivesense_sim.telemetry.sinks       # noqa: F401
import drivesense_sim.input.providers       # noqa: F401
import drivesense_sim.drives                # noqa: F401

leaked = [name for name in sys.modules if name.split(".")[0] == "pygame"]
if leaked:
    raise SystemExit("pygame leaked into the headless core: " + repr(leaked))
"""


def test_core_and_telemetry_import_without_pygame() -> None:
    result = subprocess.run(
        [sys.executable, "-c", CHECK], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_full_simulation_runs_without_pygame() -> None:
    script = """
import sys
from drivesense_sim.config import SimConfig, VehicleSpec
from drivesense_sim.drives import DEMO_DRIVE
from drivesense_sim.input.providers import ScriptedInputProvider
from drivesense_sim.session import SimulationSession

cfg = SimConfig()
session = SimulationSession(ScriptedInputProvider(DEMO_DRIVE, cfg), VehicleSpec.load(), cfg)
frames = session.advance_seconds(5.0)
assert frames, "no telemetry produced"
if any(name.split(".")[0] == "pygame" for name in sys.modules):
    raise SystemExit("pygame was imported during a headless run")
"""
    result = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stdout + result.stderr
