"""Rubric decision-list tests: one per class, boundary values, and a check
that every rule has a distinct name (the whole point of
`label_window_with_reason` is that a label always traces to one answerable
rule — two rules sharing a name would silently break that).
"""

from __future__ import annotations

from typing import get_args

from pipelines.labeling.rubric import Label, label_window_with_reason

# Baseline that falls through every rule to NORMAL/"default": no events,
# but variability just high enough to also miss the CALM rule.
_BASELINE: dict[str, float] = {
    "harsh_braking_per_min": 0.0,
    "rapid_accel_per_min": 0.0,
    "speeding_time_ratio": 0.0,
    "accel_min": -1.0,
    "accel_max": 0.8,
    "accel_std": 0.3,
    "lat_accel_max_abs": 1.0,
    "lat_accel_std": 0.35,
    "speed_cv": 0.05,
}


def _values(**overrides: float) -> dict[str, float]:
    return {**_BASELINE, **overrides}


def test_baseline_is_normal_by_default_not_by_a_rule() -> None:
    label, reason = label_window_with_reason(_values())

    assert label == "NORMAL"
    assert reason == "default"


def test_calm_requires_no_events_and_low_variability() -> None:
    label, reason = label_window_with_reason(
        _values(speed_cv=0.02, accel_std=0.15, lat_accel_std=0.2)
    )

    assert label == "CALM"
    assert reason == "steady_smooth_no_events"


def test_aggressive_harsh_braking_rate() -> None:
    label, reason = label_window_with_reason(_values(harsh_braking_per_min=2.0))

    assert label == "AGGRESSIVE"
    assert reason == "harsh_braking_per_min>=2.0"


def test_aggressive_accel_max() -> None:
    label, reason = label_window_with_reason(_values(accel_max=1.5))

    assert label == "AGGRESSIVE"
    assert reason == "accel_max>=1.5"


def test_aggressive_speeding_time_ratio() -> None:
    label, reason = label_window_with_reason(_values(speeding_time_ratio=0.5))

    assert label == "AGGRESSIVE"
    assert reason == "speeding_time_ratio>=0.5"


def test_aggressive_lateral_peak() -> None:
    label, reason = label_window_with_reason(_values(lat_accel_max_abs=2.0))

    assert label == "AGGRESSIVE"
    assert reason == "lat_accel_max_abs>=2.0"


def test_aggressive_accel_variability() -> None:
    label, reason = label_window_with_reason(_values(accel_std=0.45))

    assert label == "AGGRESSIVE"
    assert reason == "accel_std>=0.45"


def test_high_risk_harsh_braking_rate() -> None:
    label, reason = label_window_with_reason(_values(harsh_braking_per_min=6.0))

    assert label == "HIGH_RISK"
    assert reason == "harsh_braking_per_min>=6.0"


def test_high_risk_speeding_combined_with_deceleration() -> None:
    # speeding_time_ratio=0.5 alone would only match the AGGRESSIVE rule;
    # HIGH_RISK is checked first, so the combined condition wins.
    label, reason = label_window_with_reason(_values(speeding_time_ratio=0.5, accel_min=-2.0))

    assert label == "HIGH_RISK"
    assert reason == "speeding_time_ratio>=0.5 and accel_min<=-2.0"


# --- Boundary cases ---------------------------------------------------------


def test_just_below_high_risk_harsh_braking_threshold_falls_to_aggressive() -> None:
    label, _ = label_window_with_reason(_values(harsh_braking_per_min=5.999))

    assert label == "AGGRESSIVE"  # still clears the AGGRESSIVE >=2.0 rule


def test_just_below_aggressive_harsh_braking_threshold_is_not_aggressive() -> None:
    label, reason = label_window_with_reason(_values(harsh_braking_per_min=1.999))

    assert label == "NORMAL"
    assert reason == "default"


def test_calm_boundaries_are_inclusive() -> None:
    label, _ = label_window_with_reason(_values(speed_cv=0.03, accel_std=0.20, lat_accel_std=0.25))

    assert label == "CALM"


def test_just_above_calm_speed_cv_boundary_is_not_calm() -> None:
    label, reason = label_window_with_reason(
        _values(speed_cv=0.031, accel_std=0.20, lat_accel_std=0.25)
    )

    assert label == "NORMAL"
    assert reason == "default"


def test_high_risk_takes_priority_over_a_simultaneously_matching_aggressive_rule() -> None:
    # lat_accel_max_abs=2.0 alone would match AGGRESSIVE; harsh_braking_per_min=6.0
    # alone would match HIGH_RISK. HIGH_RISK must win.
    label, reason = label_window_with_reason(
        _values(lat_accel_max_abs=2.0, harsh_braking_per_min=6.0)
    )

    assert label == "HIGH_RISK"
    assert reason == "harsh_braking_per_min>=6.0"


# --- Rule-name uniqueness ---------------------------------------------------


def test_every_rule_has_a_distinct_name() -> None:
    cases: list[dict[str, float]] = [
        _values(),  # NORMAL / default
        _values(speed_cv=0.02, accel_std=0.15, lat_accel_std=0.2),  # CALM
        _values(harsh_braking_per_min=2.0),  # AGGRESSIVE
        _values(accel_max=1.5),  # AGGRESSIVE
        _values(speeding_time_ratio=0.5),  # AGGRESSIVE
        _values(lat_accel_max_abs=2.0),  # AGGRESSIVE
        _values(accel_std=0.45),  # AGGRESSIVE
        _values(harsh_braking_per_min=6.0),  # HIGH_RISK
        _values(speeding_time_ratio=0.5, accel_min=-2.0),  # HIGH_RISK
    ]

    reasons = [label_window_with_reason(case)[1] for case in cases]

    assert len(reasons) == len(set(reasons)), f"duplicate rule name among: {reasons}"


def test_label_type_covers_exactly_the_four_architecture_classes() -> None:
    assert set(get_args(Label)) == {"CALM", "NORMAL", "AGGRESSIVE", "HIGH_RISK"}
