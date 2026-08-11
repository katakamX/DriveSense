"""The risk engine's vocabulary: bands, provenance, and the assessment record.

Types only, plus the two mappings that turn a band into a number and back.
Nothing here imports the scorer, the rules or the sink, so a consumer that only
needs to *read* an assessment — the WebSocket schema, the DB model, a test —
depends on this module alone.

## Why the bands reuse the behaviour-class names

`RiskBand` is `CALM | NORMAL | AGGRESSIVE | HIGH_RISK`, the same four names the
model predicts and the rubric labels. A separate LOW/MEDIUM/HIGH/SEVERE
vocabulary would need a mapping table between two orderings of the same axis,
and a mapping table nothing checks is a bug waiting for a fifth class. One
vocabulary, one ordering, one severity scale.

## The severity scale

`BAND_SEVERITY` places the four bands at 0, 100/3, 200/3 and 100. Those are the
anchors an expected-severity score interpolates between (see
`app.core.risk.score`), and `band_for_score` cuts at the midpoints between
them, so a score sitting exactly on an anchor always maps back to its own band.
That round trip is what lets the score and the band be published together
without them ever telling different stories.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum

RISK_ENGINE_VERSION = "1"


class RiskBand(StrEnum):
    """One window's risk verdict. Ordered by severity via `BAND_ORDER`."""

    CALM = "CALM"
    NORMAL = "NORMAL"
    AGGRESSIVE = "AGGRESSIVE"
    HIGH_RISK = "HIGH_RISK"


class Provenance(StrEnum):
    """What produced the emitted band — not what happened to be loaded.

    The distinction matters because "the model is absent" and "the model was
    outvoted" are both cases where the rules alone decided, and a reader of a
    stored assessment needs `model_available` to tell them apart.

    - `RULES_ONLY` — the rules alone account for the band: either no artefact
      is loaded, or the rules landed at or above the model's band, so removing
      the model would not change the answer.
    - `MODEL_AND_RULES_AGREE` — both sources independently reached this band.
      The strongest evidence this engine can produce.
    - `MODEL_ONLY` — the model raised the band above what the rules would say.
      Possibly capped on the way up; `gated` records that separately.
    """

    RULES_ONLY = "RULES_ONLY"
    MODEL_AND_RULES_AGREE = "MODEL_AND_RULES_AGREE"
    MODEL_ONLY = "MODEL_ONLY"


BAND_ORDER: tuple[RiskBand, ...] = (
    RiskBand.CALM,
    RiskBand.NORMAL,
    RiskBand.AGGRESSIVE,
    RiskBand.HIGH_RISK,
)

_BAND_INDEX: dict[RiskBand, int] = {band: index for index, band in enumerate(BAND_ORDER)}

SCORE_MIN = 0.0
SCORE_MAX = 100.0

# Evenly spaced across [0, 100]. Even spacing is a deliberate non-claim: this
# engine does not assert that the step from AGGRESSIVE to HIGH_RISK is worse
# than the step from CALM to NORMAL, because nothing in M8 measured that.
BAND_SEVERITY: Mapping[RiskBand, float] = {
    band: SCORE_MAX * index / (len(BAND_ORDER) - 1) for index, band in enumerate(BAND_ORDER)
}

# Midpoints between adjacent anchors: 50/3, 50, 250/3.
_BAND_CUTOFFS: tuple[float, ...] = tuple(
    (BAND_SEVERITY[lower] + BAND_SEVERITY[upper]) / 2
    for lower, upper in zip(BAND_ORDER[:-1], BAND_ORDER[1:], strict=True)
)


def band_index(band: RiskBand) -> int:
    """Position on the severity axis. `CALM` is 0."""
    return _BAND_INDEX[band]


def band_for_score(score: float) -> RiskBand:
    """The band a score falls in, cutting at the midpoints between anchors.

    Inverse of `BAND_SEVERITY` in the sense that matters:
    `band_for_score(BAND_SEVERITY[b]) is b` for every band.
    """
    for cutoff, band in zip(_BAND_CUTOFFS, BAND_ORDER[:-1], strict=True):
        if score < cutoff:
            return band
    return BAND_ORDER[-1]


def band_score_range(band: RiskBand) -> tuple[float, float]:
    """The half-open `[lo, hi)` score interval that maps to `band`.

    The top band's interval is closed at `SCORE_MAX`; every other `hi` is the
    cutoff itself, which belongs to the next band up.
    """
    index = _BAND_INDEX[band]
    lo = SCORE_MIN if index == 0 else _BAND_CUTOFFS[index - 1]
    hi = SCORE_MAX if index == len(BAND_ORDER) - 1 else _BAND_CUTOFFS[index]
    return lo, hi


def clamp_into_band(score: float, band: RiskBand) -> float:
    """Move `score` the shortest distance that makes `band_for_score` return `band`.

    Called only when the gate or the rule floor has already overridden the
    band the raw score implied — see `app.core.risk.score`. `math.nextafter`
    rather than a subtracted epsilon: it lands on the largest float strictly
    below the cutoff, so the result is exact at every precision rather than
    "close enough" at this one.
    """
    lo, hi = band_score_range(band)
    ceiling = hi if band is BAND_ORDER[-1] else math.nextafter(hi, SCORE_MIN)
    return min(max(score, lo), ceiling)


def max_band(left: RiskBand, right: RiskBand) -> RiskBand:
    return left if _BAND_INDEX[left] >= _BAND_INDEX[right] else right


def min_band(left: RiskBand, right: RiskBand) -> RiskBand:
    return left if _BAND_INDEX[left] <= _BAND_INDEX[right] else right


@dataclass(frozen=True, slots=True)
class FeatureContribution:
    """One feature's signed push toward the emitted band's centered logit.

    `contribution` is in the units `app.ml.artifact` defines — standardised
    feature times class-centered coefficient — and `value` is the raw,
    un-standardised feature, because that is the number a human can check
    against the drive.
    """

    feature: str
    value: float
    contribution: float


@dataclass(frozen=True, slots=True)
class RiskAssessment:
    """One 30-second window, scored, banded, and explained.

    Everything needed to reconstruct *why* this band was emitted travels with
    it: the rules that fired, the model's own opinion, and the top feature
    contributions. A stored assessment answers the question without the
    features, the artefact, or this code being available.
    """

    # Identity — which engine, which features, which rules, which artefact.
    risk_engine_version: str
    feature_version: str
    rubric_version: str
    model_version: str | None

    # The window this describes.
    window_start: datetime
    window_end: datetime
    sample_count: int
    coverage_ratio: float

    # The verdict.
    score: float
    band: RiskBand
    confidence: float
    provenance: Provenance
    model_available: bool
    gated: bool

    # The evidence.
    rule_band: RiskBand
    matched_rules: tuple[str, ...]
    model_band: RiskBand | None
    model_score: float | None
    model_predicted_class: str | None
    probabilities: Mapping[str, float] | None
    contributions: tuple[FeatureContribution, ...] = field(default_factory=tuple)
    contributions_remainder: float = 0.0
