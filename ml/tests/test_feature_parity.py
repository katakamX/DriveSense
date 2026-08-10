"""ADR 0004's actual exit criterion: the training and inference call paths

must produce an *identical* feature vector, in identical order, from the
same telemetry.

`app.core.features.extract_features` has exactly one implementation shared
by both paths (see docs/adr/0004-shared-feature-engineering.md); what
differs between "offline" and "online" is only *how the caller gets from
its native representation to `FeatureSample` objects* before calling in:

- Offline (`ml/pipelines/featurise.py`) receives dataset rows shaped like a
  pandas DataFrame — one dict-like record per row, everything JSON-native
  (str timestamps, no `None` vs missing distinction beyond `.get()`).
- Online (live telemetry ingest) already holds `FeatureSample` instances
  built directly from `TelemetryFrame`s.

This test builds both `FeatureSample` sequences from the same fixture via
those two different construction paths and asserts `extract_features`
returns exactly equal `FeatureVector`s — no `pytest.approx`, no tolerance.
Floating-point noise between the paths would itself be a parity bug: both
paths run the identical Python arithmetic in `app.core.features.stats` on
the identical input floats, so there is no source of divergence that a
tolerance would legitimately be masking.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
from app.core.features import (
    FEATURE_NAMES,
    FeatureContext,
    FeatureSample,
    extract_features,
)

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "parity_window.json"

# Matches the fixture's engineered speeding segment (frames > 105 kph).
SPEED_LIMIT_KPH = 100.0


def _load_fixture_records() -> list[dict[str, float | str]]:
    records: list[dict[str, float | str]] = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    return records


def _offline_samples() -> list[FeatureSample]:
    """Mimic featurise.py: rows arrive as a pandas DataFrame, not objects."""
    frame = pd.DataFrame(_load_fixture_records())
    samples = []
    for row in frame.itertuples(index=False):
        samples.append(
            FeatureSample(
                recorded_at=pd.Timestamp(str(row.recorded_at)).to_pydatetime(),
                speed_kph=float(row.speed_kph),  # type: ignore[arg-type]
                accel_ms2=float(row.accel_ms2),  # type: ignore[arg-type]
                lateral_accel_ms2=float(row.lateral_accel_ms2),  # type: ignore[arg-type]
                yaw_rate_dps=float(row.yaw_rate_dps),  # type: ignore[arg-type]
                heading_deg=float(row.heading_deg),  # type: ignore[arg-type]
                lat=float(row.lat),  # type: ignore[arg-type]
                lon=float(row.lon),  # type: ignore[arg-type]
            )
        )
    return samples


def _online_samples() -> list[FeatureSample]:
    """Mimic live ingest: FeatureSamples built directly from parsed JSON."""
    from datetime import datetime

    samples = []
    for record in _load_fixture_records():
        samples.append(
            FeatureSample(
                recorded_at=datetime.fromisoformat(str(record["recorded_at"])),
                speed_kph=float(record["speed_kph"]),
                accel_ms2=float(record["accel_ms2"]),
                lateral_accel_ms2=float(record["lateral_accel_ms2"]),
                yaw_rate_dps=float(record["yaw_rate_dps"]),
                heading_deg=float(record["heading_deg"]),
                lat=float(record["lat"]),
                lon=float(record["lon"]),
            )
        )
    return samples


def test_fixture_actually_exercises_the_event_features() -> None:
    """Sanity check on the fixture itself, so a future edit that flattens it
    (and silently stops exercising harsh_braking/rapid_accel/speeding) fails
    loudly here rather than the parity test just going quiet."""
    records = _load_fixture_records()
    accels = [float(r["accel_ms2"]) for r in records]
    speeds = [float(r["speed_kph"]) for r in records]
    laterals = [float(r["lateral_accel_ms2"]) for r in records]

    assert len(records) == 300
    assert any(a <= -3.5 for a in accels), "no harsh-braking frame in fixture"
    assert any(a >= 3.0 for a in accels), "no rapid-acceleration frame in fixture"
    assert any(s > SPEED_LIMIT_KPH + 5.0 for s in speeds), "no speeding frame in fixture"
    assert any(abs(v) > 2.0 for v in laterals), "no cornering frame in fixture"


def test_offline_and_online_paths_produce_an_identical_feature_vector() -> None:
    offline_samples = _offline_samples()
    online_samples = _online_samples()

    assert offline_samples == online_samples, (
        "the two construction paths built different FeatureSamples from the same "
        "fixture — that is a bug in this test's harness, not in app.core.features"
    )

    ctx = FeatureContext(speed_limit_kph=SPEED_LIMIT_KPH, coverage_ratio=1.0)
    offline_vector = extract_features(offline_samples, ctx)
    online_vector = extract_features(online_samples, ctx)

    assert offline_vector == online_vector
    assert offline_vector.values == online_vector.values
    for name, offline_value, online_value in zip(
        FEATURE_NAMES, offline_vector.values, online_vector.values, strict=True
    ):
        # Exact equality, not approx: identical arithmetic on identical floats
        # must not differ by even the last bit.
        assert offline_value == online_value, f"{name} diverged between paths"


def test_feature_names_is_ordered_deduplicated_and_matches_vector_length() -> None:
    assert isinstance(FEATURE_NAMES, tuple)
    assert len(FEATURE_NAMES) == len(set(FEATURE_NAMES)), "FEATURE_NAMES has a duplicate"

    ctx = FeatureContext(speed_limit_kph=SPEED_LIMIT_KPH, coverage_ratio=1.0)
    vector = extract_features(_online_samples(), ctx)

    assert len(vector.values) == len(FEATURE_NAMES)
    # as_dict() zips values onto FEATURE_NAMES positionally (strict=True) —
    # a silent reordering of either side would raise there, not here.
    assert list(vector.as_dict().keys()) == list(FEATURE_NAMES)
