"""Eye-aspect-ratio, calibration, PERCLOS and blink rate.

Pure logic, deliberately free of any camera or MediaPipe dependency so it is
unit-testable against synthetic landmark arrays. PERCLOS is an established
drowsiness proxy (Wierwille et al., cited in cv/README.md) — this module
computes it, it does not invent it.

EAR thresholds are person-specific (cv/README.md): the same eyelid opening
produces different raw EAR depending on eye shape and camera angle, so a
fixed threshold misclassifies anyone but whoever it was tuned on. A short
neutral-face calibration at session start fixes that per-session.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field

import numpy as np

# Eyes-closed threshold as a fraction of the calibrated open-eye EAR.
# 0.75 is the commonly cited multiplier in EAR-based blink literature; it is
# a starting point, not a value validated against this project's own data.
DEFAULT_CLOSED_RATIO = 0.75

# Minimum consecutive closed-eye samples before counting a blink, so single-
# frame EAR noise near the threshold isn't counted as a blink.
MIN_BLINK_FRAMES = 2


def eye_aspect_ratio(eye_points: np.ndarray) -> float:
    """Standard 6-point EAR (Soukupová & Čech, 2016).

    `eye_points` is `(6, 2)`, ordered (corner, upper-1, upper-2, corner,
    lower-2, lower-1) — see `landmarks.LEFT_EYE_INDICES` / `RIGHT_EYE_INDICES`.
    """
    p1, p2, p3, p4, p5, p6 = eye_points
    vertical = np.linalg.norm(p2 - p6) + np.linalg.norm(p3 - p5)
    horizontal = np.linalg.norm(p1 - p4)
    if horizontal == 0.0:
        return 0.0
    return float(vertical / (2.0 * horizontal))


@dataclass
class Calibration:
    """Neutral-face (eyes-open) EAR baseline for one session.

    Not calibrated until `sample_count` reaches `target_samples` — before
    that, `closed_threshold` raises, so a caller cannot silently score
    against an incomplete baseline.
    """

    target_samples: int = 30
    closed_ratio: float = DEFAULT_CLOSED_RATIO
    _samples: list[float] = field(default_factory=list)

    @property
    def sample_count(self) -> int:
        return len(self._samples)

    @property
    def is_calibrated(self) -> bool:
        return self.sample_count >= self.target_samples

    def add_sample(self, ear: float) -> None:
        if not self.is_calibrated:
            self._samples.append(ear)

    @property
    def baseline_ear(self) -> float:
        if not self.is_calibrated:
            raise RuntimeError("calibration incomplete")
        return float(np.mean(self._samples))

    @property
    def closed_threshold(self) -> float:
        return self.baseline_ear * self.closed_ratio


@dataclass
class _Sample:
    ear: float
    eyes_closed: bool


class DrowsinessAggregator:
    """Rolling-window PERCLOS and blink-rate over calibrated EAR samples.

    `window_seconds` bounds the deque by wall-clock coverage rather than
    sample count, so the aggregation is correct even if the actual analysis
    rate drifts from the nominal target FPS.
    """

    def __init__(self, window_seconds: float = 60.0) -> None:
        self.window_seconds = window_seconds
        self._samples: deque[tuple[float, _Sample]] = deque()
        self._consecutive_closed = 0
        self._pending_blink = False

    def add_sample(self, timestamp_s: float, ear: float, closed_threshold: float) -> None:
        eyes_closed = ear < closed_threshold
        self._samples.append((timestamp_s, _Sample(ear=ear, eyes_closed=eyes_closed)))
        self._evict_older_than(timestamp_s)

        if eyes_closed:
            self._consecutive_closed += 1
            if self._consecutive_closed == MIN_BLINK_FRAMES:
                self._pending_blink = True
        else:
            self._consecutive_closed = 0

    def _evict_older_than(self, now_s: float) -> None:
        cutoff = now_s - self.window_seconds
        while self._samples and self._samples[0][0] < cutoff:
            self._samples.popleft()

    @property
    def perclos(self) -> float | None:
        """Fraction of window time with eyes classified closed."""
        if not self._samples:
            return None
        closed = sum(1 for _, s in self._samples if s.eyes_closed)
        return closed / len(self._samples)

    @property
    def blink_rate_per_min(self) -> float | None:
        """Blinks observed in-window, extrapolated to a per-minute rate.

        Extrapolating from a partial window (early in a session, before
        `window_seconds` of history has accumulated) inflates the rate; the
        caller is expected to treat this as unreliable until the window is
        full, the same way `perclos` above never fabricates a value on an
        empty window.
        """
        if not self._samples:
            return None
        span_s = self._samples[-1][0] - self._samples[0][0]
        if span_s <= 0.0:
            return None
        return (self._blink_count / span_s) * 60.0

    @property
    def _blink_count(self) -> int:
        # Recount from the window rather than maintaining a running counter
        # that would need its own eviction bookkeeping as old blinks age out.
        count = 0
        consecutive = 0
        for _, s in self._samples:
            if s.eyes_closed:
                consecutive += 1
                if consecutive == MIN_BLINK_FRAMES:
                    count += 1
            else:
                consecutive = 0
        return count
