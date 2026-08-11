"""The scoring function, checked against arithmetic done outside it.

The golden fixtures pin behaviour against change; the property tests state
invariants. This file is the third leg: specific numbers recomputed here from
first principles — softmax by hand, anchors by hand — so that at least some of
what the engine reports has been checked against something other than itself.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime

import pytest

from app.core.risk import assess, expected_severity
from app.core.risk.schema import (
    BAND_SEVERITY,
    RISK_ENGINE_VERSION,
    Provenance,
    RiskAssessment,
    RiskBand,
    band_for_score,
    band_score_range,
)
from app.core.risk.score import DISAGREEMENT_PENALTY, RULE_ONLY_CONFIDENCE
from app.ml.loader import ModelOutput
from tests.fixtures.risk.regenerate import BASELINE, load_toy_model, model_output

START = datetime(2026, 8, 11, 12, 0, 0, tzinfo=UTC)
END = datetime(2026, 8, 11, 12, 0, 30, tzinfo=UTC)


def score(
    features: dict[str, float] | None = None,
    *,
    use_model: bool = False,
    coverage_ratio: float = 1.0,
    top_k: int = 5,
) -> RiskAssessment:
    values = {**BASELINE, **(features or {})}
    output = model_output(load_toy_model(), values) if use_model else None
    return assess(
        features=values,
        model_output=output,
        window_start=START,
        window_end=END,
        sample_count=300,
        coverage_ratio=coverage_ratio,
        model_version="toyfixture01" if use_model else None,
        top_k=top_k,
    )


# --- the severity scale -----------------------------------------------------


def test_anchors_round_trip_through_their_own_band() -> None:
    """`band_for_score(BAND_SEVERITY[b]) is b` — the property the cutoffs exist for."""
    for band, severity in BAND_SEVERITY.items():
        assert band_for_score(severity) is band


def test_band_ranges_tile_the_scale_without_gaps_or_overlap() -> None:
    lows = [band_score_range(band)[0] for band in RiskBand]
    highs = [band_score_range(band)[1] for band in RiskBand]
    assert lows[0] == 0.0
    assert highs[-1] == 100.0
    assert highs[:-1] == lows[1:]


def test_expected_severity_is_a_convex_combination() -> None:
    """Computed here from the anchors, independently of the implementation."""
    probabilities = {"CALM": 0.1, "NORMAL": 0.2, "AGGRESSIVE": 0.3, "HIGH_RISK": 0.4}
    by_hand = 0.1 * 0.0 + 0.2 * (100 / 3) + 0.3 * (200 / 3) + 0.4 * 100.0
    assert expected_severity(probabilities) == pytest.approx(by_hand)


def test_expected_severity_normalises_an_unnormalised_distribution() -> None:
    """Doubling every weight is the same distribution and must give the same number."""
    base = {"CALM": 0.1, "NORMAL": 0.2, "AGGRESSIVE": 0.3, "HIGH_RISK": 0.4}
    doubled = {name: weight * 2 for name, weight in base.items()}
    assert expected_severity(doubled) == pytest.approx(expected_severity(base))


def test_expected_severity_rejects_classes_that_are_not_bands() -> None:
    with pytest.raises(ValueError, match="not risk bands"):
        expected_severity({"CALM": 0.5, "DROWSY": 0.5})


# --- the toy model's baseline window, recomputed by hand ---------------------


def test_baseline_probabilities_match_a_hand_computed_softmax() -> None:
    """Recompute the artefact's own arithmetic in plain Python and compare.

    Not a test of the risk engine — a test that the fixture the engine's model
    cases run through is doing what the numbers in `toy_model.json` say, so a
    later golden diff can be attributed to the engine rather than the fixture.
    """
    payload = load_toy_model()
    mean = payload["standardiser"]["mean"]
    scale = payload["standardiser"]["scale"]
    names = payload["feature_names"]
    z = [(BASELINE[name] - m) / s for name, m, s in zip(names, mean, scale, strict=True)]

    raw = [
        sum(coefficient * value for coefficient, value in zip(row, z, strict=True)) + intercept
        for row, intercept in zip(payload["coefficients"], payload["intercepts"], strict=True)
    ]
    shifted = [math.exp(value - max(raw)) for value in raw]
    total = sum(shifted)
    by_hand = {cls: value / total for cls, value in zip(payload["classes"], shifted, strict=True)}

    output = model_output(payload, BASELINE)
    for cls, probability in by_hand.items():
        assert output.probabilities[cls] == pytest.approx(probability)

    # And the score the engine reports for that window.
    severity = sum(by_hand[band.value] * BAND_SEVERITY[band] for band in RiskBand)
    assert score(use_model=True).score == pytest.approx(severity)


# --- the rule-only path -----------------------------------------------------


def test_rule_only_lands_exactly_on_the_band_anchor() -> None:
    assessment = score()
    assert assessment.model_available is False
    assert assessment.provenance is Provenance.RULES_ONLY
    assert assessment.score == BAND_SEVERITY[RiskBand.NORMAL]
    assert assessment.contributions == ()
    assert assessment.model_version is None
    assert assessment.risk_engine_version == RISK_ENGINE_VERSION


def test_rule_only_confidence_is_the_fixed_base_scaled_by_coverage() -> None:
    assert score(coverage_ratio=1.0).score is not None
    assert score(coverage_ratio=1.0).confidence == RULE_ONLY_CONFIDENCE
    assert score(coverage_ratio=0.4).confidence == pytest.approx(RULE_ONLY_CONFIDENCE * 0.4)
    assert score(coverage_ratio=0.0).confidence == 0.0


# --- the gate ---------------------------------------------------------------


def test_model_alone_cannot_reach_high_risk() -> None:
    """ADR 0007. The model's own band is still reported; the emitted one is capped."""
    assessment = score({"speed_mean": 200.0}, use_model=True)
    assert assessment.model_band is RiskBand.HIGH_RISK
    assert assessment.rule_band is RiskBand.NORMAL
    assert assessment.band is RiskBand.AGGRESSIVE
    assert assessment.gated is True
    assert assessment.provenance is Provenance.MODEL_ONLY
    # Clamped to the top of AGGRESSIVE, not left in the HIGH_RISK range.
    assert band_for_score(assessment.score) is RiskBand.AGGRESSIVE
    assert assessment.score < band_score_range(RiskBand.HIGH_RISK)[0]


def test_rules_open_the_gate_for_high_risk() -> None:
    assessment = score(
        {"speed_mean": 200.0, "speeding_time_ratio": 0.6, "accel_min": -2.5}, use_model=True
    )
    assert assessment.band is RiskBand.HIGH_RISK
    assert assessment.gated is False
    assert assessment.provenance is Provenance.MODEL_AND_RULES_AGREE


def test_rules_raise_a_band_the_model_would_not_have() -> None:
    assessment = score(
        {"speed_mean": 10.0, "speeding_time_ratio": 0.6, "accel_min": -2.5}, use_model=True
    )
    assert assessment.model_band is RiskBand.NORMAL
    assert assessment.band is RiskBand.HIGH_RISK
    # The model contributed nothing to the band, so removing it would change
    # nothing — which is exactly what RULES_ONLY claims.
    assert assessment.provenance is Provenance.RULES_ONLY
    assert assessment.model_available is True


def test_model_may_raise_the_band_up_to_the_ceiling_ungated() -> None:
    assessment = score({"speed_mean": 130.0}, use_model=True)
    assert assessment.model_band is RiskBand.AGGRESSIVE
    assert assessment.band is RiskBand.AGGRESSIVE
    assert assessment.gated is False
    assert assessment.provenance is Provenance.MODEL_ONLY
    # Ungated, so nothing clamped it: the score is the raw expected severity.
    assert assessment.score == assessment.model_score


# --- confidence -------------------------------------------------------------


def test_disagreement_penalty_applies_exactly_once() -> None:
    disagreeing = score({"speed_mean": 130.0}, use_model=True)
    top = max(disagreeing.probabilities.values())
    assert disagreeing.confidence == pytest.approx(top * DISAGREEMENT_PENALTY)

    agreeing = score({"speed_mean": 50.0}, use_model=True)
    top_agreeing = max(agreeing.probabilities.values())
    assert agreeing.confidence == pytest.approx(top_agreeing)


# --- explanations -----------------------------------------------------------


def test_contributions_explain_the_emitted_band_not_the_argmax() -> None:
    """A gated window: the model predicts HIGH_RISK, the engine emits AGGRESSIVE."""
    assessment = score({"speed_mean": 200.0}, use_model=True)
    assert assessment.model_predicted_class == "HIGH_RISK"
    assert assessment.band is RiskBand.AGGRESSIVE

    output = model_output(load_toy_model(), {**BASELINE, "speed_mean": 200.0})
    for contribution in assessment.contributions:
        assert contribution.contribution == pytest.approx(
            output.contributions["AGGRESSIVE"][contribution.feature]
        )


def test_contributions_are_ordered_by_absolute_magnitude() -> None:
    assessment = score({"speed_mean": 130.0}, use_model=True)
    magnitudes = [abs(item.contribution) for item in assessment.contributions]
    assert magnitudes == sorted(magnitudes, reverse=True)


def test_truncation_moves_the_tail_into_the_remainder() -> None:
    """Every prefix length must reconcile to the same total."""
    output = model_output(load_toy_model(), {**BASELINE, "speed_mean": 130.0})
    full = sum(output.contributions["AGGRESSIVE"].values())

    for top_k in range(0, 5):
        assessment = score({"speed_mean": 130.0}, use_model=True, top_k=top_k)
        shown = sum(item.contribution for item in assessment.contributions)
        assert len(assessment.contributions) == min(top_k, 4)
        assert shown + assessment.contributions_remainder == pytest.approx(full)


def test_contribution_values_are_the_raw_features() -> None:
    assessment = score({"speed_mean": 130.0}, use_model=True)
    for contribution in assessment.contributions:
        assert contribution.value == {**BASELINE, "speed_mean": 130.0}[contribution.feature]


# --- degenerate inputs ------------------------------------------------------


def test_zero_coverage_zeroes_confidence_without_touching_the_band() -> None:
    full = score({"speed_mean": 130.0}, use_model=True, coverage_ratio=1.0)
    empty = score({"speed_mean": 130.0}, use_model=True, coverage_ratio=0.0)
    assert empty.band is full.band
    assert empty.score == full.score
    assert empty.confidence == 0.0


def test_a_model_output_over_unknown_classes_is_rejected_loudly() -> None:
    """Better to fail the tick than to silently score a four-band scale wrong."""
    broken = ModelOutput(
        predicted_class="DROWSY",
        probabilities={"DROWSY": 0.6, "CALM": 0.4},
        contributions={"DROWSY": {}, "CALM": {}},
        centered_intercepts={"DROWSY": 0.0, "CALM": 0.0},
    )
    with pytest.raises(ValueError, match="not risk bands"):
        assess(
            features=dict(BASELINE),
            model_output=broken,
            window_start=START,
            window_end=END,
            sample_count=300,
            coverage_ratio=1.0,
        )
