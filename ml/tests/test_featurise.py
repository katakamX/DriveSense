"""featurise pipeline tests: coverage filtering and row shape.

Exercises `_windows_to_rows` directly with synthetic samples rather than
real recordings — the corpus-specific plumbing (UAH axis consensus,
simulator JSONL parsing) is covered by the adapters' own tests; this file
checks the shared windowing/threshold/row-schema logic every corpus goes
through.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.core.features import FEATURE_NAMES, FEATURE_VERSION, FeatureSample

from pipelines.featurise import COVERAGE_RATIO_THRESHOLD, PARQUET_COLUMNS, _windows_to_rows


def _samples(
    count: int, *, rate_hz: float = 10.0, start: datetime | None = None
) -> list[FeatureSample]:
    start = start or datetime(2026, 1, 1, tzinfo=UTC)
    step = timedelta(seconds=1.0 / rate_hz)
    return [
        FeatureSample(
            recorded_at=start + i * step,
            speed_kph=50.0,
            accel_ms2=0.1,
            lateral_accel_ms2=0.0,
        )
        for i in range(count)
    ]


def test_full_coverage_window_is_kept() -> None:
    # 300 samples at 10 Hz span exactly 30s: the first (0-30s) window is fully
    # covered; the second, 50%-overlapping window (15-45s) only has samples
    # for its first half and is the one this rejects.
    rows, kept, rejected = _windows_to_rows(
        corpus="test",
        driver_id="D1",
        recording_id="rec-1",
        road_type="MOTORWAY",
        speed_limit_kph=120.0,
        samples=_samples(300),
        sample_rate_hz=10.0,
        uah_label="normal",
        sha="deadbeef",
        dataset_sha256="abc123",
        generated_at="2026-01-01T00:00:00+00:00",
    )

    assert kept == 1
    assert rejected == 1
    assert len(rows) == 1
    assert rows[0]["coverage_ratio"] == 1.0


def test_gappy_window_is_rejected_below_the_threshold() -> None:
    # Half the expected samples -> coverage_ratio 0.5, well under the 0.8 policy.
    rows, kept, rejected = _windows_to_rows(
        corpus="test",
        driver_id="D1",
        recording_id="rec-2",
        road_type="MOTORWAY",
        speed_limit_kph=120.0,
        samples=_samples(150),
        sample_rate_hz=10.0,
        uah_label="normal",
        sha=None,
        dataset_sha256=None,
        generated_at="2026-01-01T00:00:00+00:00",
    )

    assert kept == 0
    assert rejected == 1
    assert rows == []


def test_coverage_ratio_threshold_is_the_documented_policy_value() -> None:
    assert COVERAGE_RATIO_THRESHOLD == 0.8


def test_row_schema_matches_parquet_columns() -> None:
    rows, _, _ = _windows_to_rows(
        corpus="uah",
        driver_id="D1",
        recording_id="rec-1",
        road_type="MOTORWAY",
        speed_limit_kph=120.0,
        samples=_samples(300),
        sample_rate_hz=10.0,
        uah_label="aggressive",
        sha="deadbeef",
        dataset_sha256="abc123",
        generated_at="2026-01-01T00:00:00+00:00",
    )

    assert set(rows[0].keys()) == set(PARQUET_COLUMNS)
    for name in FEATURE_NAMES:
        assert isinstance(rows[0][name], float)
    assert rows[0]["feature_version"] == FEATURE_VERSION
    assert rows[0]["uah_label"] == "aggressive"
    assert rows[0]["rubric_label"] is None  # labelling rubric is not implemented yet
