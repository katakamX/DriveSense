"""Determinism and regression protection for the physics model.

Two distinct guarantees:

* **Determinism** — the same script produces bit-identical telemetry within a
  run. Asserted exactly.
* **Regression** — the committed fixture still describes the model's
  behaviour. Asserted with a small tolerance, because floating-point
  transcendentals are not guaranteed bit-identical across platforms and this
  suite must pass on both Windows and Linux CI.

A failure here means the physics changed. Review why, then regenerate:
    python -c "from tests.golden import write_fixture; write_fixture()"
"""

from __future__ import annotations

import pytest

from tests.golden import build_summary, load_fixture, run_golden

TOLERANCE = 1e-3


def test_scripted_run_is_bit_exact_repeatable() -> None:
    first = run_golden()
    second = run_golden()

    assert len(first) == len(second)
    assert [frame.model_dump_json() for frame in first] == [
        frame.model_dump_json() for frame in second
    ]


def test_golden_frame_count_and_gear_changes_are_unchanged() -> None:
    summary = build_summary()
    expected = load_fixture()

    assert summary["frame_count"] == expected["frame_count"]
    assert summary["gear_sequence"] == expected["gear_sequence"]
    assert summary["gear_changes"] == expected["gear_changes"]


@pytest.mark.parametrize(
    "metric",
    [
        "max_speed_kph",
        "max_rpm",
        "max_accel_ms2",
        "min_accel_ms2",
        "max_abs_lateral_ms2",
        "final_distance_m",
        "final_speed_kph",
        "final_rpm",
        "final_coolant_c",
    ],
)
def test_golden_metrics_are_unchanged(metric: str) -> None:
    summary = build_summary()
    expected = load_fixture()

    assert summary[metric] == pytest.approx(expected[metric], abs=TOLERANCE)


def test_golden_drive_exercises_the_whole_model() -> None:
    """The fixture is only useful if the drive actually covers the behaviour."""
    frames = run_golden()

    assert {frame.gear for frame in frames} >= {0, 1, 2, 3, 4}
    assert max(frame.speed_kph for frame in frames) > 50.0
    assert min(frame.accel_ms2 for frame in frames) < -1.0  # braking
    assert max(frame.accel_ms2 for frame in frames) > 0.5  # accelerating
    assert any(frame.gear == 0 and frame.engine_rpm > 2000 for frame in frames)  # neutral revving
    assert any(abs(frame.lateral_accel_ms2) > 0.5 for frame in frames)  # cornering
    assert any(frame.speed_kph < 0.1 for frame in frames[-40:])  # came to a stop
