"""The trip-level fold: the specific behaviours the property tests don't pin down.

`test_risk_properties.py` proves the fold's algebra — order independence,
boundedness, the empty identity. This file checks the choices: coverage
weighting, the tail statistics published beside the mean, and what a trip that
never produced a window reports.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.core.risk import RiskAssessment, assess, fold, fold_all, summarise
from app.core.risk.aggregate import EMPTY, finalise
from app.core.risk.schema import RiskBand
from tests.fixtures.risk.regenerate import BASELINE

START = datetime(2026, 8, 11, 12, 0, 0, tzinfo=UTC)

CALM_WINDOW = {"speed_cv": 0.02, "accel_std": 0.15, "lat_accel_std": 0.20}
AGGRESSIVE_WINDOW = {"accel_max": 1.6}
HIGH_RISK_WINDOW = {"speeding_time_ratio": 0.6, "accel_min": -2.5}


def window(overrides: dict[str, float], *, coverage: float = 1.0, index: int = 0) -> RiskAssessment:
    """A rule-only assessment — enough to exercise the fold without a model."""
    return assess(
        features={**BASELINE, **overrides},
        model_output=None,
        window_start=START + timedelta(seconds=index),
        window_end=START + timedelta(seconds=index + 30),
        sample_count=int(300 * coverage),
        coverage_ratio=coverage,
    )


def test_an_unstarted_trip_reports_nothing_rather_than_zero() -> None:
    summary = finalise(EMPTY)
    assert summary.window_count == 0
    assert summary.trip_score is None
    assert summary.trip_band is None
    assert summary.mean_score is None
    assert summary.max_score is None
    assert summary.band_counts == dict.fromkeys(RiskBand, 0)


def test_coverage_weighting_discounts_thin_windows() -> None:
    """A window built from a handful of samples is weaker evidence, and counts as less."""
    strong_calm = window(CALM_WINDOW, coverage=1.0, index=0)
    thin_high_risk = window(HIGH_RISK_WINDOW, coverage=0.1, index=1)

    summary = summarise([strong_calm, thin_high_risk])
    # Unweighted this would be (0 + 100) / 2 = 50.0.
    assert summary.mean_score == pytest.approx(50.0)
    # Weighted: (0*1.0 + 100*0.1) / 1.1.
    assert summary.trip_score == pytest.approx(100 * 0.1 / 1.1)
    assert summary.trip_score < summary.mean_score


def test_the_worst_window_survives_the_mean() -> None:
    """Forty calm windows and one severe one. The mean hides it; max_score does not."""
    batch = [window(CALM_WINDOW, index=index) for index in range(40)]
    batch.append(window(HIGH_RISK_WINDOW, index=40))

    summary = summarise(batch)
    assert summary.trip_band is RiskBand.CALM
    assert summary.trip_score == pytest.approx(100 / 41)
    assert summary.max_score == 100.0
    assert summary.high_risk_window_ratio == pytest.approx(1 / 41)
    assert summary.band_counts[RiskBand.HIGH_RISK] == 1


def test_band_counts_track_every_band() -> None:
    batch = [
        window(CALM_WINDOW, index=0),
        window({}, index=1),
        window(AGGRESSIVE_WINDOW, index=2),
        window(HIGH_RISK_WINDOW, index=3),
        window(HIGH_RISK_WINDOW, index=4),
    ]
    summary = summarise(batch)
    assert summary.band_counts == {
        RiskBand.CALM: 1,
        RiskBand.NORMAL: 1,
        RiskBand.AGGRESSIVE: 1,
        RiskBand.HIGH_RISK: 2,
    }
    assert summary.high_risk_window_ratio == pytest.approx(0.4)


def test_window_bounds_span_the_whole_trip() -> None:
    batch = [window({}, index=index) for index in (5, 0, 3)]
    summary = summarise(batch)
    assert summary.first_window_start == START
    assert summary.last_window_end == START + timedelta(seconds=35)


def test_model_and_gated_ratios_are_zero_without_an_artefact() -> None:
    summary = summarise([window({}, index=index) for index in range(4)])
    assert summary.model_window_ratio == 0.0
    assert summary.gated_window_ratio == 0.0


def test_zero_coverage_throughout_falls_back_to_the_unweighted_mean() -> None:
    """Weighting by a quantity that is uniformly zero would divide by it."""
    batch = [
        window(CALM_WINDOW, coverage=0.0, index=0),
        window(HIGH_RISK_WINDOW, coverage=0.0, index=1),
    ]
    summary = summarise(batch)
    assert summary.trip_score == pytest.approx(50.0)
    assert summary.trip_score == summary.mean_score


def test_the_accumulator_is_immutable() -> None:
    """`fold` returns a new accumulator; the sink relies on the old one being safe."""
    first = fold(EMPTY, window({}, index=0))
    second = fold(first, window({}, index=1))
    assert first.window_count == 1
    assert second.window_count == 2
    assert EMPTY.window_count == 0


def test_fold_all_matches_repeated_fold() -> None:
    batch = [window(CALM_WINDOW, index=0), window(AGGRESSIVE_WINDOW, index=1)]
    stepwise = EMPTY
    for assessment in batch:
        stepwise = fold(stepwise, assessment)
    assert stepwise == fold_all(batch)


def test_out_of_range_coverage_is_clamped_before_weighting() -> None:
    """A coverage ratio above 1.0 must not let one window outvote the rest."""
    inflated = assess(
        features={**BASELINE, **HIGH_RISK_WINDOW},
        model_output=None,
        window_start=START,
        window_end=START + timedelta(seconds=30),
        sample_count=99999,
        coverage_ratio=50.0,
    )
    summary = summarise([window(CALM_WINDOW, index=1), inflated])
    assert summary.trip_score == pytest.approx(50.0)
