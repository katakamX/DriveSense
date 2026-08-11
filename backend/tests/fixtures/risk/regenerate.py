"""Regenerate the risk-engine golden fixtures.

    python -m tests.fixtures.risk.regenerate      # from backend/

The case *inputs* are defined here, in Python, because each one exists to
exercise something specific and that intent belongs in a comment next to it.
The JSON files this writes are generated artefacts: inputs and the outputs the
current engine produces for them.

**What a golden test proves, and what it does not.** These expectations were
produced by the code they test, so they cannot show the engine is correct —
they show it has not *changed*. That is their whole job: any edit to a
threshold, an anchor, the gate or the top-k rule turns up here as a diff that
has to be looked at and justified rather than discovered later in a dashboard.
Correctness is argued elsewhere: `test_risk_properties.py` for the invariants
that must hold over every input, and the hand-computed assertions in
`test_risk_score.py` for specific numbers a human checked by hand.

Regenerating is therefore never the fix for a failing golden on its own. Read
the diff first; if it is intended, regenerate and commit the diff *with* the
change that caused it.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np

from app.core.risk import assess, summarise
from app.core.risk.schema import RiskAssessment
from app.ml import artifact as artifact_module
from app.ml.loader import ModelOutput

FIXTURE_DIR = Path(__file__).parent
TOY_MODEL_PATH = FIXTURE_DIR / "toy_model.json"

WINDOW_START = datetime(2026, 8, 11, 12, 0, 0, tzinfo=UTC)
WINDOW_END = datetime(2026, 8, 11, 12, 0, 30, tzinfo=UTC)

# An ordinary window: nothing the rules care about, and mid-range for every
# feature the toy model reads. Every case below is this, plus overrides, so a
# case's diff from "unremarkable driving" is visible at a glance.
BASELINE: dict[str, float] = {
    "speed_mean": 50.0,
    "speed_std": 5.0,
    "speed_max": 62.0,
    "speed_cv": 0.10,
    "speed_range": 18.0,
    "stop_ratio": 0.0,
    "accel_mean_abs": 0.25,
    "accel_std": 0.30,
    "accel_max": 0.90,
    "accel_min": -0.80,
    "accel_rms": 0.32,
    "accel_time_ratio": 0.18,
    "brake_time_ratio": 0.15,
    "jerk_std": 0.90,
    "jerk_max_abs": 3.10,
    "lat_accel_std": 0.35,
    "lat_accel_max_abs": 1.00,
    "lat_accel_time_ratio": 0.0,
    "accel_magnitude_mean": 0.50,
    "accel_magnitude_max": 1.40,
    "yaw_rate_std": 0.0,
    "heading_change_rate": 0.0,
    "harsh_braking_per_min": 0.0,
    "rapid_accel_per_min": 0.0,
    "speeding_time_ratio": 0.0,
    "event_rate_per_min": 0.0,
}

# The toy model reads only `speed_mean` of the four rule inputs' complement,
# which is what makes the model's band steerable independently of the rules':
# these three values drive it to roughly NORMAL, AGGRESSIVE and HIGH_RISK.
SPEED_MEAN_MODEL_NORMAL = 50.0
SPEED_MEAN_MODEL_AGGRESSIVE = 130.0
SPEED_MEAN_MODEL_HIGH_RISK = 200.0

# (name, feature overrides, use_model, coverage_ratio, sample_count, top_k, why)
CASES: list[tuple[str, dict[str, float], bool, float, int, int, str]] = [
    # --- the rule layer, one case per rule ID, no model ---------------------
    (
        "rules_default_normal",
        {},
        False,
        1.0,
        300,
        5,
        "Nothing fires. NORMAL is a default, not a threshold, so matched_rules is empty.",
    ),
    (
        "rules_calm",
        {"speed_cv": 0.02, "accel_std": 0.15, "lat_accel_std": 0.20},
        False,
        1.0,
        300,
        5,
        "The three-way CALM conjunction, the only positive rule below NORMAL.",
    ),
    (
        "rules_aggressive_harsh_braking",
        {"harsh_braking_per_min": 2.1},
        False,
        1.0,
        300,
        5,
        "One debounced brake application in a 30 s window.",
    ),
    (
        "rules_aggressive_accel_max",
        {"accel_max": 1.6},
        False,
        1.0,
        300,
        5,
        "accel_max replaced rapid_accel_per_min, which is constant on UAH.",
    ),
    (
        "rules_aggressive_speeding",
        {"speeding_time_ratio": 0.6},
        False,
        1.0,
        300,
        5,
        "Sustained speeding alone is AGGRESSIVE; with hard deceleration it is HIGH_RISK.",
    ),
    (
        "rules_aggressive_lat_accel",
        {"lat_accel_max_abs": 2.1},
        False,
        1.0,
        300,
        5,
        "Cornering peak.",
    ),
    (
        "rules_aggressive_accel_std",
        {"accel_std": 0.50},
        False,
        1.0,
        300,
        5,
        "Longitudinal variability.",
    ),
    (
        "rules_high_risk_compound",
        {"speeding_time_ratio": 0.6, "accel_min": -2.5},
        False,
        1.0,
        300,
        5,
        "The only HIGH_RISK rule: too fast, reacting late.",
    ),
    (
        "rules_multiple_matched",
        {
            "speeding_time_ratio": 0.6,
            "accel_min": -2.5,
            "accel_max": 1.6,
            "accel_std": 0.50,
            "harsh_braking_per_min": 2.1,
        },
        False,
        1.0,
        300,
        5,
        "Four rules fire. The band is the most severe; every reason still travels.",
    ),
    (
        "rules_calm_and_aggressive_cofire",
        {"speed_cv": 0.02, "accel_std": 0.15, "lat_accel_std": 0.20, "accel_max": 1.6},
        False,
        1.0,
        300,
        5,
        "A single spike inside otherwise calm driving: both fire, AGGRESSIVE wins the band.",
    ),
    # --- threshold boundaries, ±one representable step ----------------------
    (
        "boundary_harsh_braking_exact",
        {"harsh_braking_per_min": 2.0},
        False,
        1.0,
        300,
        5,
        "The cutoff is >=, so exactly 2.0 fires.",
    ),
    (
        "boundary_harsh_braking_below",
        {"harsh_braking_per_min": 1.999},
        False,
        1.0,
        300,
        5,
        "One step under the same cutoff does not.",
    ),
    (
        "boundary_high_risk_exact",
        {"speeding_time_ratio": 0.5, "accel_min": -2.0},
        False,
        1.0,
        300,
        5,
        "Both HIGH_RISK conditions exactly at their cutoffs.",
    ),
    (
        "boundary_high_risk_accel_min_above",
        {"speeding_time_ratio": 0.5, "accel_min": -1.999},
        False,
        1.0,
        300,
        5,
        "Deceleration one step short: falls through to the AGGRESSIVE speeding rule.",
    ),
    # --- the model path, and the gate ---------------------------------------
    (
        "model_agrees_normal",
        {"speed_mean": SPEED_MEAN_MODEL_NORMAL},
        True,
        1.0,
        300,
        5,
        "Both sources reach NORMAL independently — the strongest evidence available.",
    ),
    (
        "model_only_raises_to_aggressive",
        {"speed_mean": SPEED_MEAN_MODEL_AGGRESSIVE},
        True,
        1.0,
        300,
        5,
        "The model raises the band above the rules. Not gated: AGGRESSIVE is the ceiling.",
    ),
    (
        "model_gated_at_aggressive",
        {"speed_mean": SPEED_MEAN_MODEL_HIGH_RISK},
        True,
        1.0,
        300,
        5,
        "ADR 0007: the model alone reaches HIGH_RISK and is capped at AGGRESSIVE.",
    ),
    (
        "model_below_rules",
        {
            "speed_mean": 10.0,
            "speeding_time_ratio": 0.6,
            "accel_min": -2.5,
        },
        True,
        1.0,
        300,
        5,
        "Rules say HIGH_RISK, model says NORMAL. Rules win; provenance is RULES_ONLY.",
    ),
    (
        "model_and_rules_agree_high_risk",
        {
            "speed_mean": SPEED_MEAN_MODEL_HIGH_RISK,
            "speeding_time_ratio": 0.6,
            "accel_min": -2.5,
        },
        True,
        1.0,
        300,
        5,
        "The only way HIGH_RISK is ever emitted with the model contributing.",
    ),
    # --- coverage and window quality ----------------------------------------
    (
        "coverage_zero",
        {"speed_mean": SPEED_MEAN_MODEL_AGGRESSIVE},
        True,
        0.0,
        0,
        5,
        "Zero coverage drives confidence to zero without touching the band.",
    ),
    (
        "coverage_half",
        {"speed_mean": SPEED_MEAN_MODEL_AGGRESSIVE},
        True,
        0.5,
        150,
        5,
        "Half the expected samples, half the confidence.",
    ),
    (
        "coverage_rule_only_half",
        {},
        False,
        0.5,
        150,
        5,
        "The rule-only path is scaled by coverage too, from its fixed 0.5 base.",
    ),
    (
        "degenerate_two_sample_window",
        {},
        True,
        0.0067,
        2,
        5,
        "MIN_SAMPLES in the ticker: a trip that just started, not an error.",
    ),
    # --- explanation truncation ----------------------------------------------
    (
        "top_k_one",
        {"speed_mean": SPEED_MEAN_MODEL_AGGRESSIVE},
        True,
        1.0,
        300,
        1,
        "One contribution shown; the remaining three sum into the remainder.",
    ),
    (
        "top_k_zero",
        {"speed_mean": SPEED_MEAN_MODEL_AGGRESSIVE},
        True,
        1.0,
        300,
        0,
        "Nothing shown; the remainder carries the entire centered-logit decomposition.",
    ),
]

# Twenty-five one-second windows walking a trip from calm through a
# rules-driven HIGH_RISK window and back, at varying coverage. Exercises the
# fold over every band, both provenance sources, gated and ungated windows.
TRIP_STEPS: list[tuple[dict[str, float], bool, float]] = [
    ({"speed_cv": 0.02, "accel_std": 0.15, "lat_accel_std": 0.20}, False, 1.0),
    ({"speed_cv": 0.02, "accel_std": 0.15, "lat_accel_std": 0.20}, False, 0.8),
    ({}, False, 1.0),
    ({}, True, 1.0),
    ({"speed_mean": SPEED_MEAN_MODEL_AGGRESSIVE}, True, 1.0),
    ({"speed_mean": SPEED_MEAN_MODEL_HIGH_RISK}, True, 0.9),
    ({"accel_max": 1.6}, False, 1.0),
    ({"speeding_time_ratio": 0.6, "accel_min": -2.5}, False, 1.0),
    ({"speeding_time_ratio": 0.6, "accel_min": -2.5}, True, 0.6),
    ({"harsh_braking_per_min": 2.1}, False, 1.0),
    ({}, True, 0.4),
    ({}, False, 1.0),
    ({"speed_cv": 0.02, "accel_std": 0.15, "lat_accel_std": 0.20}, False, 1.0),
]


def load_toy_model() -> dict[str, Any]:
    """The committed stand-in artefact. Public: the tests build from it too."""
    return artifact_module.read_model_json(TOY_MODEL_PATH)


def model_output(payload: dict[str, Any], features: dict[str, float]) -> ModelOutput:
    """Run the toy artefact without disturbing whatever the process has loaded."""
    names: list[str] = list(payload["feature_names"])
    classes: list[str] = list(payload["classes"])
    row = np.asarray([[float(features[name]) for name in names]], dtype=np.float64)

    probabilities = artifact_module.predict_proba(payload, row)[0]
    contributions = artifact_module.feature_contributions(payload, row)[0]
    intercepts = artifact_module.centered_intercepts(payload)

    return ModelOutput(
        predicted_class=classes[int(probabilities.argmax())],
        probabilities={cls: float(p) for cls, p in zip(classes, probabilities, strict=True)},
        contributions={
            cls: {name: float(value) for name, value in zip(names, row_c, strict=True)}
            for cls, row_c in zip(classes, contributions, strict=True)
        },
        centered_intercepts={
            cls: float(value) for cls, value in zip(classes, intercepts, strict=True)
        },
    )


def _serialise(assessment: RiskAssessment) -> dict[str, Any]:
    data = asdict(assessment)
    data["window_start"] = assessment.window_start.isoformat()
    data["window_end"] = assessment.window_end.isoformat()
    data["band"] = assessment.band.value
    data["rule_band"] = assessment.rule_band.value
    data["model_band"] = assessment.model_band.value if assessment.model_band else None
    data["provenance"] = assessment.provenance.value
    data["matched_rules"] = list(assessment.matched_rules)
    data["contributions"] = [dict(item) for item in data["contributions"]]
    return data


def build_windows() -> dict[str, Any]:
    payload = load_toy_model()
    cases: list[dict[str, Any]] = []

    for name, overrides, use_model, coverage, samples, top_k, why in CASES:
        features = {**BASELINE, **overrides}
        output = model_output(payload, features) if use_model else None
        assessment = assess(
            features=features,
            model_output=output,
            window_start=WINDOW_START,
            window_end=WINDOW_END,
            sample_count=samples,
            coverage_ratio=coverage,
            model_version="toyfixture01" if use_model else None,
            top_k=top_k,
        )
        cases.append(
            {
                "name": name,
                "why": why,
                "features": overrides,
                "use_model": use_model,
                "coverage_ratio": coverage,
                "sample_count": samples,
                "top_k": top_k,
                "expected": _serialise(assessment),
            }
        )

    return {
        "note": (
            "Generated by tests/fixtures/risk/regenerate.py. Expectations were produced by the "
            "engine under test: they pin behaviour against change, they do not prove it correct. "
            "See the module docstring."
        ),
        "window_start": WINDOW_START.isoformat(),
        "window_end": WINDOW_END.isoformat(),
        "model_version": "toyfixture01",
        "baseline_features": BASELINE,
        "cases": cases,
    }


def build_trip() -> dict[str, Any]:
    payload = load_toy_model()
    assessments: list[RiskAssessment] = []
    steps: list[dict[str, Any]] = []

    for index, (overrides, use_model, coverage) in enumerate(TRIP_STEPS):
        features = {**BASELINE, **overrides}
        output = model_output(payload, features) if use_model else None
        assessment = assess(
            features=features,
            model_output=output,
            window_start=WINDOW_START.replace(second=index),
            window_end=WINDOW_END.replace(second=index),
            sample_count=int(300 * coverage),
            coverage_ratio=coverage,
            model_version="toyfixture01" if use_model else None,
        )
        assessments.append(assessment)
        steps.append(
            {
                "features": overrides,
                "use_model": use_model,
                "coverage_ratio": coverage,
                "band": assessment.band.value,
                "score": assessment.score,
            }
        )

    summary = summarise(assessments)
    return {
        "note": "Generated by tests/fixtures/risk/regenerate.py — see build_windows's note.",
        "steps": steps,
        "expected_summary": {
            "risk_engine_version": summary.risk_engine_version,
            "window_count": summary.window_count,
            "trip_score": summary.trip_score,
            "trip_band": summary.trip_band.value if summary.trip_band else None,
            "mean_score": summary.mean_score,
            "max_score": summary.max_score,
            "band_counts": {band.value: count for band, count in summary.band_counts.items()},
            "high_risk_window_ratio": summary.high_risk_window_ratio,
            "gated_window_ratio": summary.gated_window_ratio,
            "model_window_ratio": summary.model_window_ratio,
            "first_window_start": summary.first_window_start.isoformat()
            if summary.first_window_start
            else None,
            "last_window_end": summary.last_window_end.isoformat()
            if summary.last_window_end
            else None,
        },
    }


def main() -> None:
    (FIXTURE_DIR / "golden_windows.json").write_text(
        json.dumps(build_windows(), indent=2) + "\n", encoding="utf-8"
    )
    (FIXTURE_DIR / "golden_trip.json").write_text(
        json.dumps(build_trip(), indent=2) + "\n", encoding="utf-8"
    )
    print(f"wrote {len(CASES)} window cases and {len(TRIP_STEPS)} trip steps to {FIXTURE_DIR}")


if __name__ == "__main__":
    main()
