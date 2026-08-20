from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.core.obd.features import (
    OBD_FEATURE_VERSION,
    assess_obd_window,
    obd_rows_to_feature_samples,
)
from app.core.obd.parse import parse_obd_csv
from app.core.risk.schema import Provenance, RiskBand

FIXTURE = Path(__file__).parent / "fixtures" / "sample_obd.csv"
BASE_TIME = datetime(2024, 1, 1, tzinfo=UTC)


def _fixture_rows():
    return parse_obd_csv(FIXTURE.read_text())


# --- Noise: the thing STEP4_FINDINGS.md flagged as a real, solvable problem -


def test_naive_differentiation_would_be_implausibly_noisy() -> None:
    """Documents the problem `obd_rows_to_feature_samples` solves: raw
    frame-to-frame differentiation at the file's native ~0.03s cadence blows
    past real vehicle physics on this exact fixture."""
    rows = _fixture_rows()
    naive_accels = []
    for prev, cur in zip(rows, rows[1:], strict=False):
        dt = cur.time_s - prev.time_s
        if dt > 0:
            naive_accels.append(((cur.speed_kmh - prev.speed_kmh) / 3.6) / dt)
    assert max(naive_accels) > 20.0
    assert min(naive_accels) < -20.0


def test_resampled_acceleration_is_physically_plausible() -> None:
    rows = _fixture_rows()
    samples = obd_rows_to_feature_samples(rows, base_time=BASE_TIME)
    accels = [s.accel_ms2 for s in samples]
    # A real car's plausible envelope, generously bounded — not the ±30 m/s^2
    # the naive differentiation above produces on the same file.
    assert max(accels) < 10.0
    assert min(accels) > -10.0


def test_resampling_reduces_sample_count_toward_10hz() -> None:
    rows = _fixture_rows()
    samples = obd_rows_to_feature_samples(rows, base_time=BASE_TIME)
    # ~53s of driving at 10 Hz is on the order of 530 samples, not the
    # source file's 1780 rows at ~33 Hz.
    assert 400 < len(samples) < 600


def test_too_short_for_one_differentiated_sample_returns_empty() -> None:
    rows = _fixture_rows()[:1]
    assert obd_rows_to_feature_samples(rows, base_time=BASE_TIME) == []


# --- assess_obd_window: RULES_ONLY by construction, never a model opinion --


def test_whole_fixture_is_rules_only_with_no_model() -> None:
    rows = _fixture_rows()
    samples = obd_rows_to_feature_samples(rows, base_time=BASE_TIME)
    result = assess_obd_window(
        samples,
        window_start=samples[0].recorded_at,
        window_end=samples[-1].recorded_at,
        speed_limit_kph=100.0,
    )
    assert result.provenance is Provenance.RULES_ONLY
    assert result.model_available is False
    assert result.gated is False
    assert result.model_band is None
    assert result.model_score is None
    assert result.probabilities is None
    assert result.feature_version == OBD_FEATURE_VERSION
    # The known hard-brake segment (Speed_kmh 83 -> 72 over ~0.8s, well past
    # HARSH_BRAKING_ACCEL_MS2) should be enough to keep this window off CALM.
    assert result.band is not RiskBand.CALM


def test_matched_rules_never_mention_lateral_acceleration() -> None:
    rows = _fixture_rows()
    samples = obd_rows_to_feature_samples(rows, base_time=BASE_TIME)
    result = assess_obd_window(
        samples,
        window_start=samples[0].recorded_at,
        window_end=samples[-1].recorded_at,
        speed_limit_kph=100.0,
    )
    for rule in result.matched_rules:
        assert "lat_accel" not in rule


def test_empty_samples_is_rejected() -> None:
    with pytest.raises(ValueError, match="at least one sample"):
        assess_obd_window([], window_start=BASE_TIME, window_end=BASE_TIME, speed_limit_kph=100.0)


def test_coverage_ratio_reflects_expected_sample_count() -> None:
    rows = _fixture_rows()
    samples = obd_rows_to_feature_samples(rows, base_time=BASE_TIME)
    half = samples[: len(samples) // 2]
    result = assess_obd_window(
        half,
        window_start=half[0].recorded_at,
        window_end=half[-1].recorded_at,
        speed_limit_kph=100.0,
        expected_sample_count=len(samples),
    )
    assert result.coverage_ratio == pytest.approx(0.5, abs=0.02)
