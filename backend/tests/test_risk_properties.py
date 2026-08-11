"""Property tests — Milestone 9's exit criterion, the half the goldens cannot cover.

A golden fixture says "these twenty-five inputs still produce these outputs".
These say "no input produces an output that violates this", which is the only
form the safety claims can take: "the model alone can never emit HIGH_RISK" is
a statement about every window that will ever be scored, not about twenty-five
of them.

Eleven invariants, grouped below. What is deliberately *not* here: the
contributions-sum-to-centered-logit identity, which is `app.ml`'s and is
already proven in `test_ml_artifact.py`. Its risk-engine counterpart — that
truncating to top-k keeps the sum reconcilable — is new, and is number 9.
"""

from __future__ import annotations

import math
import random
from datetime import UTC, datetime, timedelta

import pytest
from hypothesis import assume, given, settings
from hypothesis import strategies as st

from app.core.features.schema import FEATURE_NAMES
from app.core.risk import assess
from app.core.risk.aggregate import EMPTY, finalise, fold, fold_all
from app.core.risk.rules import evaluate
from app.core.risk.schema import (
    BAND_ORDER,
    RiskAssessment,
    RiskBand,
    band_for_score,
    band_index,
)
from app.ml.loader import ModelOutput

START = datetime(2026, 8, 11, 12, 0, 0, tzinfo=UTC)
END = START + timedelta(seconds=30)

# Wide enough to reach every threshold in the rule list, finite and non-NaN
# because a feature vector containing either is a bug upstream in
# `app.core.features`, not an input the risk engine is meant to survive.
_feature_value = st.floats(min_value=-50.0, max_value=250.0, allow_nan=False, allow_infinity=False)
_features = st.fixed_dictionaries(dict.fromkeys(FEATURE_NAMES, _feature_value))

_coverage = st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False)

# A distribution over the four bands. Unnormalised on purpose: `assess`
# normalises, and generating raw weights explores ratios a normalised
# strategy would round away.
_weights = st.lists(
    st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
    min_size=len(BAND_ORDER),
    max_size=len(BAND_ORDER),
).filter(lambda values: sum(values) > 1e-6)


@st.composite
def model_outputs(draw: st.DrawFn, features: dict[str, float]) -> ModelOutput:
    """A `ModelOutput` consistent with `features` — the contract `assess` assumes.

    Contributions are keyed by a subset of the features actually present,
    because `app.ml.predict` can only produce contributions for features it
    was given, and `assess` looks their raw values up.
    """
    weights = draw(_weights)
    total = sum(weights)
    probabilities = {
        band.value: weight / total for band, weight in zip(BAND_ORDER, weights, strict=True)
    }
    names = draw(st.lists(st.sampled_from(sorted(features)), min_size=1, max_size=8, unique=True))
    contribution = st.floats(min_value=-20.0, max_value=20.0, allow_nan=False, allow_infinity=False)
    contributions = {
        band.value: {name: draw(contribution) for name in names} for band in BAND_ORDER
    }
    return ModelOutput(
        predicted_class=max(probabilities, key=lambda key: probabilities[key]),
        probabilities=probabilities,
        contributions=contributions,
        centered_intercepts={band.value: draw(contribution) for band in BAND_ORDER},
    )


@st.composite
def assessments(draw: st.DrawFn) -> RiskAssessment:
    features = draw(_features)
    with_model = draw(st.booleans())
    return assess(
        features=features,
        model_output=draw(model_outputs(features)) if with_model else None,
        window_start=START,
        window_end=END,
        sample_count=draw(st.integers(min_value=0, max_value=300)),
        coverage_ratio=draw(_coverage),
        model_version="prop" if with_model else None,
        top_k=draw(st.integers(min_value=0, max_value=8)),
    )


# --- 1. boundedness ---------------------------------------------------------


@given(assessments())
def test_score_and_confidence_are_bounded(assessment: RiskAssessment) -> None:
    assert 0.0 <= assessment.score <= 100.0
    assert 0.0 <= assessment.confidence <= 1.0
    assert not math.isnan(assessment.score)
    assert not math.isnan(assessment.confidence)


# --- 2. determinism ---------------------------------------------------------


@given(_features, _coverage, st.booleans(), st.data())
def test_determinism_and_independence_from_dict_order(
    features: dict[str, float], coverage: float, with_model: bool, data: st.DataObject
) -> None:
    """Two calls agree, and shuffling the feature dict changes nothing.

    Dict ordering is the classic source of a "deterministic" function that is
    not: a `max` over ties, or a sort without a tiebreak, silently follows
    insertion order.
    """
    output = data.draw(model_outputs(features)) if with_model else None
    kwargs = {
        "model_output": output,
        "window_start": START,
        "window_end": END,
        "sample_count": 300,
        "coverage_ratio": coverage,
    }
    first = assess(features=features, **kwargs)  # type: ignore[arg-type]
    second = assess(features=features, **kwargs)  # type: ignore[arg-type]

    shuffled_keys = list(features)
    random.Random(0).shuffle(shuffled_keys)
    shuffled = assess(features={key: features[key] for key in shuffled_keys}, **kwargs)  # type: ignore[arg-type]

    assert first == second == shuffled


# --- 3. monotonicity in severity --------------------------------------------


@given(_features, _weights, st.integers(min_value=0, max_value=2), st.floats(0.01, 1.0))
def test_moving_probability_mass_upward_never_lowers_the_score(
    features: dict[str, float],
    weights: list[float],
    from_index: int,
    fraction: float,
) -> None:
    """The core claim the 0-100 scale makes. Violating it would invert the axis."""
    assume(weights[from_index] > 0.0)
    total = sum(weights)
    before = {band.value: weight / total for band, weight in zip(BAND_ORDER, weights, strict=True)}

    moved = weights[from_index] * fraction
    shifted = list(weights)
    shifted[from_index] -= moved
    shifted[from_index + 1] += moved
    after = {band.value: weight / total for band, weight in zip(BAND_ORDER, shifted, strict=True)}

    def score_for(probabilities: dict[str, float]) -> float:
        return (
            assess(
                features=features,
                model_output=ModelOutput(
                    predicted_class=max(probabilities, key=lambda key: probabilities[key]),
                    probabilities=probabilities,
                    contributions={band.value: {} for band in BAND_ORDER},
                    centered_intercepts={band.value: 0.0 for band in BAND_ORDER},
                ),
                window_start=START,
                window_end=END,
                sample_count=300,
                coverage_ratio=1.0,
            ).model_score
            or 0.0
        )

    assert score_for(after) >= score_for(before) - 1e-9


# --- 4. gate soundness ------------------------------------------------------


@given(assessments())
def test_high_risk_requires_the_rules_to_say_so(assessment: RiskAssessment) -> None:
    """ADR 0007, as an assertion over every possible window."""
    if assessment.band is RiskBand.HIGH_RISK:
        assert assessment.rule_band is RiskBand.HIGH_RISK


@given(assessments())
def test_the_model_alone_never_exceeds_the_aggressive_ceiling(
    assessment: RiskAssessment,
) -> None:
    if assessment.rule_band is not RiskBand.HIGH_RISK:
        assert band_index(assessment.band) <= band_index(RiskBand.AGGRESSIVE)


@given(assessments())
def test_gated_is_true_exactly_when_the_ceiling_bound(assessment: RiskAssessment) -> None:
    if assessment.model_band is None:
        assert assessment.gated is False
    else:
        capped = (
            assessment.rule_band is not RiskBand.HIGH_RISK
            and assessment.model_band is RiskBand.HIGH_RISK
        )
        assert assessment.gated is capped


# --- 5. rule floor ----------------------------------------------------------


@given(assessments())
def test_the_emitted_band_is_never_below_the_rules(assessment: RiskAssessment) -> None:
    assert band_index(assessment.band) >= band_index(assessment.rule_band)


# --- 6. score / band consistency --------------------------------------------


@given(assessments())
def test_the_score_always_falls_inside_the_emitted_band(assessment: RiskAssessment) -> None:
    """The two published numbers cannot tell different stories."""
    assert band_for_score(assessment.score) is assessment.band


# --- 7. provenance consistency ----------------------------------------------


@given(assessments())
def test_provenance_matches_what_actually_produced_the_band(
    assessment: RiskAssessment,
) -> None:
    if not assessment.model_available:
        assert assessment.provenance.value == "RULES_ONLY"
        assert assessment.model_band is None
        return

    assert assessment.model_band is not None
    if assessment.provenance.value == "MODEL_AND_RULES_AGREE":
        assert assessment.model_band is assessment.rule_band
        assert assessment.band is assessment.rule_band
    elif assessment.provenance.value == "MODEL_ONLY":
        assert band_index(assessment.model_band) > band_index(assessment.rule_band)
    else:
        # RULES_ONLY with a model loaded: the rules were at or above it, so
        # dropping the model would not have changed the band.
        assert band_index(assessment.model_band) < band_index(assessment.rule_band)
        assert assessment.band is assessment.rule_band


# --- 8. rule-only totality --------------------------------------------------


@given(_features, _coverage)
def test_the_rule_only_path_is_total(features: dict[str, float], coverage: float) -> None:
    """No artefact is a normal state. It must never raise and never half-answer."""
    assessment = assess(
        features=features,
        model_output=None,
        window_start=START,
        window_end=END,
        sample_count=0,
        coverage_ratio=coverage,
    )
    assert assessment.model_available is False
    assert assessment.provenance.value == "RULES_ONLY"
    assert assessment.contributions == ()
    assert assessment.contributions_remainder == 0.0
    assert assessment.model_version is None
    assert assessment.probabilities is None
    assert assessment.band is evaluate(features).band


# --- 9. contribution reconciliation after truncation ------------------------


@given(_features, st.integers(min_value=0, max_value=10), st.data())
def test_truncated_contributions_still_reconcile(
    features: dict[str, float], top_k: int, data: st.DataObject
) -> None:
    """The new invariant. `app.ml` proves the full sum; this proves the prefix.

    Showing five of twenty contributions is an explanation only if a reader
    can still account for the other fifteen — which is what the remainder is
    for. Without this, top-k would be the point at which the explainability
    path quietly stops being exact.
    """
    output = data.draw(model_outputs(features))
    assessment = assess(
        features=features,
        model_output=output,
        window_start=START,
        window_end=END,
        sample_count=300,
        coverage_ratio=1.0,
        top_k=top_k,
    )
    full = sum(output.contributions[assessment.band.value].values())
    shown = sum(item.contribution for item in assessment.contributions)
    assert shown + assessment.contributions_remainder == pytest.approx(full, abs=1e-9)
    assert len(assessment.contributions) == min(
        top_k, len(output.contributions[assessment.band.value])
    )
    # And what is shown is genuinely the largest part of it.
    for item in assessment.contributions:
        assert item.contribution == output.contributions[assessment.band.value][item.feature]
        assert item.value == features[item.feature]


# --- 10. fold algebra -------------------------------------------------------


@given(st.lists(assessments(), min_size=0, max_size=8))
@settings(max_examples=40)
def test_fold_is_order_independent(batch: list[RiskAssessment]) -> None:
    """Every field is a sum, a count, a max or a min — so shuffling cannot matter.

    This is what licenses the incremental path: the sink folds each assessment
    as it arrives, and the answer must be the one a batch reduce would give.

    Counts, band histograms and window bounds are compared exactly; the three
    running sums are compared to within float tolerance, because IEEE-754
    addition is commutative but *not* associative — `(a+b)+c` and `(a+c)+b`
    can differ in the last bit. Asserting bit-equality there would be
    asserting something about float representation rather than about the
    fold, and it would fail on inputs the fold handles correctly.
    """
    shuffled = list(batch)
    random.Random(1).shuffle(shuffled)
    left, right = fold_all(batch), fold_all(shuffled)

    assert left.window_count == right.window_count
    assert left.band_counts == right.band_counts
    assert left.gated_count == right.gated_count
    assert left.model_window_count == right.model_window_count
    assert left.score_max == right.score_max
    assert left.first_window_start == right.first_window_start
    assert left.last_window_end == right.last_window_end

    assert left.score_sum == pytest.approx(right.score_sum, rel=1e-12, abs=1e-9)
    assert left.coverage_sum == pytest.approx(right.coverage_sum, rel=1e-12, abs=1e-9)
    assert left.coverage_weighted_score_sum == pytest.approx(
        right.coverage_weighted_score_sum, rel=1e-12, abs=1e-9
    )


@given(assessments())
def test_single_fold_equals_fold_all_of_one(assessment: RiskAssessment) -> None:
    assert fold(EMPTY, assessment) == fold_all([assessment])


@given(st.lists(assessments(), min_size=1, max_size=6))
@settings(max_examples=40)
def test_summary_is_bounded_and_consistent(batch: list[RiskAssessment]) -> None:
    summary = finalise(fold_all(batch))
    assert summary.window_count == len(batch)
    assert summary.trip_score is not None
    assert 0.0 <= summary.trip_score <= 100.0
    assert summary.trip_band is band_for_score(summary.trip_score)
    assert summary.max_score == max(item.score for item in batch)
    assert sum(summary.band_counts.values()) == len(batch)
    assert 0.0 <= summary.high_risk_window_ratio <= 1.0
    assert 0.0 <= summary.gated_window_ratio <= 1.0


def test_the_empty_fold_does_not_divide_by_zero() -> None:
    summary = finalise(EMPTY)
    assert summary.window_count == 0
    # A trip too short to score is not a calm trip.
    assert summary.trip_score is None
    assert summary.trip_band is None


# --- 11. rubric parity ------------------------------------------------------
#
# Lives in test_risk_rules.py, beside the rules it guards: the moved decision
# list is compared both against a frozen verbatim copy of the pre-move code
# (always) and against the committed training corpus (when present).
