"""Sequence of samples -> fixed-span, overlapping windows.

Pure function: no ring buffer, no I/O, no dependency on how the samples
arrived. Both the offline pipeline (a whole recording, windowed at once) and
future online inference (a ring buffer's contents, windowed on each tick)
call this the same way.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta

from app.core.features.schema import FeatureSample

DEFAULT_SPAN_S = 30.0
DEFAULT_OVERLAP = 0.5


@dataclass(frozen=True)
class Window:
    """One windowed span of samples, not yet reduced to a feature vector."""

    window_start: datetime
    window_end: datetime
    samples: tuple[FeatureSample, ...]
    sample_count: int
    coverage_ratio: float


def make_windows(
    samples: list[FeatureSample],
    *,
    span_s: float = DEFAULT_SPAN_S,
    overlap: float = DEFAULT_OVERLAP,
    expected_rate_hz: float,
) -> list[Window]:
    """Split `samples` into fixed-span windows advancing by `span_s * (1 - overlap)`.

    `expected_rate_hz` is the input's nominal sample rate, used only to
    compute `coverage_ratio` (actual samples / expected samples for a fully
    sampled span) — it is never inferred from the data, since a gap in the
    data is exactly what coverage_ratio needs to detect.

    Windows are half-open [start, end) and always start at the first
    sample's timestamp, so alignment is deterministic given the input.
    """
    if not samples:
        return []
    if span_s <= 0:
        raise ValueError("span_s must be positive")
    if not 0.0 <= overlap < 1.0:
        raise ValueError("overlap must be in [0.0, 1.0)")

    ordered = sorted(samples, key=lambda s: s.recorded_at)
    stride_s = span_s * (1.0 - overlap)
    expected_count = span_s * expected_rate_hz

    t0 = ordered[0].recorded_at
    t_last = ordered[-1].recorded_at

    windows: list[Window] = []
    window_start = t0
    while window_start <= t_last:
        window_end = window_start + timedelta(seconds=span_s)
        window_samples = tuple(s for s in ordered if window_start <= s.recorded_at < window_end)
        if window_samples:
            coverage_ratio = len(window_samples) / expected_count if expected_count > 0 else 0.0
            windows.append(
                Window(
                    window_start=window_start,
                    window_end=window_end,
                    samples=window_samples,
                    sample_count=len(window_samples),
                    coverage_ratio=coverage_ratio,
                )
            )
        window_start = window_start + timedelta(seconds=stride_s)

    return windows
