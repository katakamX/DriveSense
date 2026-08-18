"""Trip-level fold: many window assessments reduced to one trip summary.

Incremental rather than batch. A trip is scored once per second for as long as
it runs, and holding every assessment in memory so a final `reduce` can see
them all would make the memory cost of a trip a function of its length — the
exact shape ADR 0001 pushed out of the ingest path. `fold` takes an
accumulator and one assessment and returns a new accumulator, so the running
state is a fixed number of floats no matter how long the drive.

Every field of `TripRiskAccumulator` is a sum, a count, a max or a min, which
makes `fold` commutative and associative. That is not an accident and it is
not decoration: it is what makes the incremental path and a batch `fold_all`
provably the same computation, and it is asserted as a property rather than
assumed.

## Why the headline is coverage-weighted, and why the tail is published beside it

`trip_score` weights each window by its `coverage_ratio`. A window built from
four samples and a window built from three hundred are not equally strong
evidence, and `coverage_ratio` already measures exactly that difference, so
using it costs nothing and ignoring it would silently let a sparse window at
the start of a trip count as much as a full one in the middle.

`max_score` and `high_risk_window_ratio` are reported alongside the mean, not
folded into it. A single genuinely severe minute inside a forty-minute drive
is invisible in any mean, and burying it is precisely the failure this
milestone exists to avoid. The mean says what the trip was like; the tail says
what the worst of it was; a consumer that only reads one of them is choosing
which question to ask.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
from datetime import datetime

from app.core.risk.schema import (
    BAND_ORDER,
    RISK_ENGINE_VERSION,
    RiskAssessment,
    RiskBand,
    band_for_score,
    band_index,
)


@dataclass(frozen=True, slots=True)
class TripRiskAccumulator:
    """Running trip state. Immutable; `fold` returns a new one."""

    risk_engine_version: str = RISK_ENGINE_VERSION
    window_count: int = 0
    score_sum: float = 0.0
    score_max: float = 0.0
    coverage_weighted_score_sum: float = 0.0
    coverage_sum: float = 0.0
    gated_count: int = 0
    model_window_count: int = 0
    # Aligned 1:1 with `BAND_ORDER`, so equality and ordering are structural
    # rather than dependent on a dict's insertion order.
    band_counts: tuple[int, ...] = (0,) * len(BAND_ORDER)
    first_window_start: datetime | None = None
    last_window_end: datetime | None = None


EMPTY = TripRiskAccumulator()


@dataclass(frozen=True, slots=True)
class TripRiskSummary:
    """The finished trip verdict.

    `trip_score` and `trip_band` are `None` for a trip that produced no
    windows — a trip too short to score is not a calm trip, and the columns
    that store these are nullable for that reason.
    """

    risk_engine_version: str
    window_count: int
    trip_score: float | None
    trip_band: RiskBand | None
    mean_score: float | None
    max_score: float | None
    band_counts: Mapping[RiskBand, int]
    high_risk_window_ratio: float
    gated_window_ratio: float
    model_window_ratio: float
    first_window_start: datetime | None
    last_window_end: datetime | None


def fold(accumulator: TripRiskAccumulator, assessment: RiskAssessment) -> TripRiskAccumulator:
    """Add one window's assessment to the running trip state."""
    counts = list(accumulator.band_counts)
    counts[band_index(assessment.band)] += 1

    starts = [assessment.window_start]
    if accumulator.first_window_start is not None:
        starts.append(accumulator.first_window_start)
    ends = [assessment.window_end]
    if accumulator.last_window_end is not None:
        ends.append(accumulator.last_window_end)

    coverage = min(max(assessment.coverage_ratio, 0.0), 1.0)

    return replace(
        accumulator,
        window_count=accumulator.window_count + 1,
        score_sum=accumulator.score_sum + assessment.score,
        score_max=max(accumulator.score_max, assessment.score),
        coverage_weighted_score_sum=(
            accumulator.coverage_weighted_score_sum + assessment.score * coverage
        ),
        coverage_sum=accumulator.coverage_sum + coverage,
        gated_count=accumulator.gated_count + (1 if assessment.gated else 0),
        model_window_count=(
            accumulator.model_window_count + (1 if assessment.model_available else 0)
        ),
        band_counts=tuple(counts),
        first_window_start=min(starts),
        last_window_end=max(ends),
    )


def fold_all(assessments: Iterable[RiskAssessment]) -> TripRiskAccumulator:
    """Batch form of `fold`, starting from `EMPTY`. Equal to folding one at a time."""
    accumulator = EMPTY
    for assessment in assessments:
        accumulator = fold(accumulator, assessment)
    return accumulator


def finalise(accumulator: TripRiskAccumulator) -> TripRiskSummary:
    """Turn running state into the trip's published verdict.

    Falls back to the unweighted mean when total coverage is zero — possible
    only if every window was empty, in which case weighting by a quantity that
    is uniformly zero would divide by it rather than express a preference.
    """
    band_counts = dict(zip(BAND_ORDER, accumulator.band_counts, strict=True))

    if accumulator.window_count == 0:
        return TripRiskSummary(
            risk_engine_version=accumulator.risk_engine_version,
            window_count=0,
            trip_score=None,
            trip_band=None,
            mean_score=None,
            max_score=None,
            band_counts=band_counts,
            high_risk_window_ratio=0.0,
            gated_window_ratio=0.0,
            model_window_ratio=0.0,
            first_window_start=None,
            last_window_end=None,
        )

    if accumulator.coverage_sum > 0.0:
        trip_score = accumulator.coverage_weighted_score_sum / accumulator.coverage_sum
    else:
        trip_score = accumulator.score_sum / accumulator.window_count
    # Every window score is already within [0, 100]; the weighted division
    # above is a sum-of-in-range-values divided by a positive weight, which
    # is mathematically in range too, but float rounding can walk the result
    # a ULP past 100.0. Clamp rather than let that leak into the published
    # score and its band.
    trip_score = min(max(trip_score, 0.0), 100.0)

    return TripRiskSummary(
        risk_engine_version=accumulator.risk_engine_version,
        window_count=accumulator.window_count,
        trip_score=trip_score,
        trip_band=band_for_score(trip_score),
        mean_score=accumulator.score_sum / accumulator.window_count,
        max_score=accumulator.score_max,
        band_counts=band_counts,
        high_risk_window_ratio=(band_counts[RiskBand.HIGH_RISK] / accumulator.window_count),
        gated_window_ratio=accumulator.gated_count / accumulator.window_count,
        model_window_ratio=accumulator.model_window_count / accumulator.window_count,
        first_window_start=accumulator.first_window_start,
        last_window_end=accumulator.last_window_end,
    )


def summarise(assessments: Iterable[RiskAssessment]) -> TripRiskSummary:
    """`finalise(fold_all(...))`, for callers that already hold every window."""
    return finalise(fold_all(assessments))


__all__ = [
    "EMPTY",
    "TripRiskAccumulator",
    "TripRiskSummary",
    "finalise",
    "fold",
    "fold_all",
    "summarise",
]
