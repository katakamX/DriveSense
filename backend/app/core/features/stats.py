"""Stdlib-only numeric reductions.

No numpy, no pandas: ADR 0004 requires the offline and online feature paths
to produce *identical* vectors, and numpy/pandas reductions can differ from
stdlib `statistics` in their last bits due to pairwise summation. Using
`statistics` on both call sites removes that whole class of flakiness.
"""

import math
import statistics
from collections.abc import Sequence


def mean(values: Sequence[float]) -> float:
    return statistics.fmean(values) if values else 0.0


def std(values: Sequence[float]) -> float:
    """Population standard deviation. 0.0 for empty or single-value input."""
    if len(values) < 1:
        return 0.0
    return statistics.pstdev(values)


def maximum(values: Sequence[float]) -> float:
    return max(values) if values else 0.0


def minimum(values: Sequence[float]) -> float:
    return min(values) if values else 0.0


def rms(values: Sequence[float]) -> float:
    if not values:
        return 0.0
    return math.sqrt(sum(v * v for v in values) / len(values))


def percentile(values: Sequence[float], p: float) -> float:
    """Linear-interpolated percentile, p in [0, 100]. 0.0 for empty input."""
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    rank = (p / 100.0) * (len(ordered) - 1)
    lower = math.floor(rank)
    upper = math.ceil(rank)
    if lower == upper:
        return ordered[int(rank)]
    fraction = rank - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction


def time_above_threshold(values: Sequence[float], threshold: float) -> float:
    """Fraction of samples strictly above `threshold`. 0.0 for empty input."""
    if not values:
        return 0.0
    return sum(1 for v in values if v > threshold) / len(values)


def time_below_threshold(values: Sequence[float], threshold: float) -> float:
    """Fraction of samples strictly below `threshold`. 0.0 for empty input."""
    if not values:
        return 0.0
    return sum(1 for v in values if v < threshold) / len(values)
