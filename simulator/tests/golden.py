"""Golden-run summary builder.

Kept out of the package proper: this is test infrastructure. Regenerate the
fixture deliberately, never automatically, after reviewing why the physics
changed:

    python -c "from tests.golden import write_fixture; write_fixture()"
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from drivesense_contracts import TelemetryFrame
from drivesense_sim.config import SimConfig, VehicleSpec
from drivesense_sim.drives import DEMO_DRIVE
from drivesense_sim.input.providers import ScriptedInputProvider
from drivesense_sim.session import SimulationSession

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "golden_run.json"
STARTED_AT = datetime(2026, 1, 1, tzinfo=UTC)
TRIP_ID = "golden-run"
CHECKPOINT_EVERY = 50

TRACKED = (
    "sim_t",
    "speed_kph",
    "engine_rpm",
    "accel_ms2",
    "throttle_pct",
    "brake_pct",
    "clutch_pct",
    "engine_load_pct",
    "steering_deg",
    "distance_m",
)


def run_golden() -> list[TelemetryFrame]:
    config = SimConfig()
    session = SimulationSession(
        ScriptedInputProvider(DEMO_DRIVE, config),
        VehicleSpec.load(),
        config,
        trip_id=TRIP_ID,
        started_at=STARTED_AT,
    )
    return session.advance_seconds(sum(step.duration_s for step in DEMO_DRIVE))


def _digest(frames: list[TelemetryFrame]) -> str:
    hasher = hashlib.sha256()
    for frame in frames:
        row = [frame.gear, *(round(getattr(frame, field), 3) for field in TRACKED)]
        hasher.update(json.dumps(row, separators=(",", ":")).encode())
    return hasher.hexdigest()


def build_summary(frames: list[TelemetryFrame] | None = None) -> dict[str, Any]:
    frames = frames if frames is not None else run_golden()
    final = frames[-1]
    return {
        "frame_count": len(frames),
        "digest_sha256": _digest(frames),
        "gear_sequence": sorted({frame.gear for frame in frames}),
        "gear_changes": [
            [index, frame.gear]
            for index, frame in enumerate(frames)
            if index > 0 and frame.gear != frames[index - 1].gear
        ],
        "max_speed_kph": round(max(frame.speed_kph for frame in frames), 4),
        "max_rpm": round(max(frame.engine_rpm for frame in frames), 4),
        "max_accel_ms2": round(max(frame.accel_ms2 for frame in frames), 4),
        "min_accel_ms2": round(min(frame.accel_ms2 for frame in frames), 4),
        "max_abs_lateral_ms2": round(max(abs(frame.lateral_accel_ms2) for frame in frames), 4),
        "final_distance_m": round(final.distance_m, 4),
        "final_speed_kph": round(final.speed_kph, 4),
        "final_rpm": round(final.engine_rpm, 4),
        "final_coolant_c": round(final.coolant_c or 0.0, 4),
    }


def write_fixture() -> Path:
    FIXTURE_PATH.parent.mkdir(parents=True, exist_ok=True)
    FIXTURE_PATH.write_text(json.dumps(build_summary(), indent=2) + "\n", encoding="utf-8")
    return FIXTURE_PATH


def load_fixture() -> dict[str, Any]:
    data: dict[str, Any] = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    return data
