"""The scoring function: one window in, one `RiskAssessment` out.

Pure and synchronous. No clock, no settings, no I/O — every input the result
depends on is an argument, which is what makes the golden fixtures expressible
as `(kwargs, expected)` pairs rather than as a running system.

## The score is expected severity, not `p(HIGH_RISK)`

`BAND_SEVERITY` puts the four bands at 0, 100/3, 200/3 and 100, and the score
is the probability-weighted mean of those anchors. Three things follow for
free: it is bounded in [0, 100] because it is a convex combination; it moves
continuously as the probabilities move; and shifting probability mass toward a
more severe class can never lower it.

The alternative — read `p(HIGH_RISK)` and scale it — was rejected because that
head is the single least trustworthy number the model produces. `HIGH_RISK`
precision is 0.105 on real telemetry (docs/model-card.md), so a score keyed to
it spikes on the one output known to be wrong nine times in ten. Expected
severity spreads the same information across all four heads, where the model
card's one genuinely positive finding lives: the severity *ordering* survives
transfer to real data even though the operating point does not.

## Rules gate the top band

`HIGH_RISK` cannot be emitted unless the rules independently say `HIGH_RISK`.
The model alone caps at `AGGRESSIVE`. That is ADR 0007, and the number behind
it is the same 0.105 — against a rubric compound rule that fires on 12 UAH
windows and on no `normal`-labelled window at all. Rules can also raise the
band; they cannot lower one below `AGGRESSIVE`, because a model shouting about
a window the rules have nothing to say about is still information.

## Band is derived from score, never from argmax

`model_band` is `band_for_score(model_score)`, not `argmax(probabilities)`.
Those disagree more often than they look like they should — a window at
`{CALM: .4, NORMAL: .3, AGGRESSIVE: .2, HIGH_RISK: .1}` has argmax `CALM` and
expected severity 33.3, which is `NORMAL`. Deriving the band from the score
makes `band_for_score(score) == band` true by construction instead of by a
clamp applied afterwards, so the two published numbers cannot contradict each
other. The raw argmax is still reported, as `model_predicted_class`, because
hiding it would make the model's own opinion unrecoverable from a stored
assessment.

Clamping therefore happens only when the gate or the rule floor has already
moved the band away from what the score implied — which is exactly the case
where the two numbers would otherwise disagree.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime

from app.core.features.schema import FEATURE_VERSION
from app.core.risk import rules
from app.core.risk.schema import (
    BAND_SEVERITY,
    RISK_ENGINE_VERSION,
    SCORE_MAX,
    SCORE_MIN,
    FeatureContribution,
    Provenance,
    RiskAssessment,
    RiskBand,
    band_for_score,
    band_index,
    clamp_into_band,
    max_band,
    min_band,
)
from app.ml import ModelOutput

# A decision list has no calibrated probability. Rather than manufacture one
# out of how far a feature cleared its threshold — a number that would look
# like a confidence without being one — the rule-only path reports a fixed
# middling value and lets `model_available` explain it.
RULE_ONLY_CONFIDENCE = 0.5

# Applied when the model's band and the rules' band differ. Multiplicative, so
# confidence stays in [0, 1] without a clamp. 0.6 is a judgement call, not a
# measurement: the two sources disagreeing is the situation this engine knows
# least about, and the honest response is to say so rather than to pick the
# winner's own confidence and present it unchanged.
DISAGREEMENT_PENALTY = 0.6

# How many feature contributions travel with an assessment. Five fits a
# dashboard panel and a log line; the rest are summed into
# `contributions_remainder` so the arithmetic still reconciles.
DEFAULT_TOP_K = 5


def expected_severity(probabilities: Mapping[str, float]) -> float:
    """Probability-weighted mean of the band anchors, in [0, 100].

    Normalises first. A softmax sums to 1.0 only up to float error, and a
    hand-built distribution in a test may not sum to 1.0 at all; normalising
    makes boundedness structural rather than approximate.
    """
    unknown = sorted(name for name in probabilities if name not in RiskBand.__members__)
    if unknown:
        raise ValueError(
            f"model classes {unknown} are not risk bands — the artefact's classes must be "
            f"{[band.value for band in RiskBand]}"
        )

    total = sum(probabilities.values())
    if total <= 0.0:
        raise ValueError("probabilities sum to zero; cannot form an expected severity")

    severity = sum(weight * BAND_SEVERITY[RiskBand(name)] for name, weight in probabilities.items())
    # The convex combination is already in range; the clamp only absorbs float
    # error at the endpoints.
    return min(max(severity / total, SCORE_MIN), SCORE_MAX)


def _contributions_for(
    band: RiskBand,
    model_output: ModelOutput,
    features: Mapping[str, float],
    top_k: int,
) -> tuple[tuple[FeatureContribution, ...], float]:
    """Top-`k` contributions toward `band`, plus the sum of the tail.

    Explains the band that was *emitted*, not the model's argmax: showing a
    driver one verdict and the reasons for a different one is worse than
    showing no reasons. When the emitted band is not one the artefact scores —
    possible only for a malformed artefact, since `expected_severity` has
    already rejected non-band classes — there is nothing truthful to show, so
    this returns nothing rather than the nearest available class's reasons.
    """
    per_feature = model_output.contributions.get(band.value)
    if not per_feature:
        return (), 0.0

    # Ties broken by name so the output does not depend on dict ordering.
    ordered = sorted(per_feature.items(), key=lambda item: (-abs(item[1]), item[0]))
    head, tail = ordered[:top_k], ordered[top_k:]
    emitted = tuple(
        FeatureContribution(feature=name, value=float(features[name]), contribution=float(value))
        for name, value in head
    )
    return emitted, float(sum(value for _, value in tail))


def assess(
    *,
    features: Mapping[str, float],
    model_output: ModelOutput | None,
    window_start: datetime,
    window_end: datetime,
    sample_count: int,
    coverage_ratio: float,
    model_version: str | None = None,
    top_k: int = DEFAULT_TOP_K,
) -> RiskAssessment:
    """Score one feature window.

    `features` must be `FeatureVector.as_dict()`-shaped, and when
    `model_output` is present it must be the output of running the model over
    *these* features — `app.ml.predict` guarantees every artefact feature name
    is present, and the contribution values are looked up against it.

    `model_output=None` is the rule-only path and a normal state, not an
    error: a fresh checkout has no artefact (see `app.ml.loader`).
    """
    rule_outcome = rules.evaluate(features)
    rule_band = rule_outcome.band
    coverage_factor = min(max(coverage_ratio, 0.0), 1.0)

    if model_output is None:
        return RiskAssessment(
            risk_engine_version=RISK_ENGINE_VERSION,
            feature_version=FEATURE_VERSION,
            rubric_version=rules.RUBRIC_VERSION,
            model_version=None,
            window_start=window_start,
            window_end=window_end,
            sample_count=sample_count,
            coverage_ratio=coverage_ratio,
            score=BAND_SEVERITY[rule_band],
            band=rule_band,
            confidence=RULE_ONLY_CONFIDENCE * coverage_factor,
            provenance=Provenance.RULES_ONLY,
            model_available=False,
            gated=False,
            rule_band=rule_band,
            matched_rules=rule_outcome.matched,
            model_band=None,
            model_score=None,
            model_predicted_class=None,
            probabilities=None,
        )

    model_score = expected_severity(model_output.probabilities)
    model_band = band_for_score(model_score)

    # The gate. Rules raise the floor; they also cap the ceiling at
    # AGGRESSIVE unless they independently reached HIGH_RISK themselves.
    ceiling = RiskBand.HIGH_RISK if rule_band is RiskBand.HIGH_RISK else RiskBand.AGGRESSIVE
    capped = min_band(model_band, ceiling)
    band = max_band(rule_band, capped)
    gated = capped is not model_band

    # Only moves the score when the band moved out from under it.
    score = model_score if band is model_band else clamp_into_band(model_score, band)

    if band_index(model_band) > band_index(rule_band):
        provenance = Provenance.MODEL_ONLY
    elif model_band is rule_band:
        provenance = Provenance.MODEL_AND_RULES_AGREE
    else:
        provenance = Provenance.RULES_ONLY

    top_probability = max(model_output.probabilities.values()) / sum(
        model_output.probabilities.values()
    )
    agreement_factor = 1.0 if model_band is rule_band else DISAGREEMENT_PENALTY
    contributions, remainder = _contributions_for(band, model_output, features, top_k)

    return RiskAssessment(
        risk_engine_version=RISK_ENGINE_VERSION,
        feature_version=FEATURE_VERSION,
        rubric_version=rules.RUBRIC_VERSION,
        model_version=model_version,
        window_start=window_start,
        window_end=window_end,
        sample_count=sample_count,
        coverage_ratio=coverage_ratio,
        score=score,
        band=band,
        confidence=min(max(top_probability * coverage_factor * agreement_factor, 0.0), 1.0),
        provenance=provenance,
        model_available=True,
        gated=gated,
        rule_band=rule_band,
        matched_rules=rule_outcome.matched,
        model_band=model_band,
        model_score=model_score,
        model_predicted_class=model_output.predicted_class,
        probabilities=dict(model_output.probabilities),
        contributions=contributions,
        contributions_remainder=remainder,
    )
