"""Tests for pure logic: EAR, calibration, PERCLOS, blink rate.

All synthetic landmark data — no camera or MediaPipe involved, so these
exercise `drowsiness.py` in isolation. Camera capture (`capture.py`) and the
MediaPipe wrapper (`landmarks.py`) are not covered here: they need a real
camera/frame source and are exercised by the manual `main.py` run instead.
"""

import numpy as np
import pytest

from drowsiness import (
    MIN_BLINK_FRAMES,
    Calibration,
    DrowsinessAggregator,
    eye_aspect_ratio,
)


def _eye(width: float, height: float) -> np.ndarray:
    """A synthetic 6-point eye contour with the given horizontal/vertical span.

    Ordered (corner, upper-1, upper-2, corner, lower-2, lower-1) to match
    `landmarks.LEFT_EYE_INDICES`. `height` controls eyelid opening: 0 collapses
    the eye to a horizontal line (EAR == 0), matching a fully closed eye.
    """
    half_w = width / 2.0
    return np.array(
        [
            (-half_w, 0.0),  # corner
            (-half_w / 2.0, -height / 2.0),  # upper-1
            (half_w / 2.0, -height / 2.0),  # upper-2
            (half_w, 0.0),  # corner
            (half_w / 2.0, height / 2.0),  # lower-2
            (-half_w / 2.0, height / 2.0),  # lower-1
        ]
    )


class TestEyeAspectRatio:
    def test_open_eye_has_positive_ear(self):
        open_eye = _eye(width=10.0, height=4.0)
        assert eye_aspect_ratio(open_eye) > 0.0

    def test_closed_eye_has_zero_ear(self):
        closed_eye = _eye(width=10.0, height=0.0)
        assert eye_aspect_ratio(closed_eye) == pytest.approx(0.0)

    def test_more_open_eye_has_higher_ear(self):
        narrow = _eye(width=10.0, height=2.0)
        wide = _eye(width=10.0, height=6.0)
        assert eye_aspect_ratio(wide) > eye_aspect_ratio(narrow)

    def test_degenerate_zero_width_eye_does_not_divide_by_zero(self):
        degenerate = _eye(width=0.0, height=4.0)
        assert eye_aspect_ratio(degenerate) == 0.0


class TestCalibration:
    def test_not_calibrated_before_target_samples(self):
        calibration = Calibration(target_samples=5)
        for _ in range(4):
            calibration.add_sample(0.3)
        assert not calibration.is_calibrated

    def test_calibrated_after_target_samples(self):
        calibration = Calibration(target_samples=5)
        for _ in range(5):
            calibration.add_sample(0.3)
        assert calibration.is_calibrated

    def test_baseline_ear_raises_before_calibrated(self):
        calibration = Calibration(target_samples=5)
        calibration.add_sample(0.3)
        with pytest.raises(RuntimeError):
            _ = calibration.baseline_ear

    def test_baseline_is_mean_of_calibration_samples(self):
        calibration = Calibration(target_samples=3)
        for ear in (0.2, 0.3, 0.4):
            calibration.add_sample(ear)
        assert calibration.baseline_ear == pytest.approx(0.3)

    def test_closed_threshold_scales_by_closed_ratio(self):
        calibration = Calibration(target_samples=1, closed_ratio=0.5)
        calibration.add_sample(0.4)
        assert calibration.closed_threshold == pytest.approx(0.2)

    def test_samples_beyond_target_are_ignored(self):
        calibration = Calibration(target_samples=2)
        calibration.add_sample(0.2)
        calibration.add_sample(0.4)
        calibration.add_sample(1000.0)  # would blow up the mean if counted
        assert calibration.baseline_ear == pytest.approx(0.3)


class TestDrowsinessAggregator:
    def test_perclos_none_on_empty_window(self):
        aggregator = DrowsinessAggregator(window_seconds=60.0)
        assert aggregator.perclos is None
        assert aggregator.blink_rate_per_min is None

    def test_perclos_zero_when_eyes_always_open(self):
        aggregator = DrowsinessAggregator(window_seconds=60.0)
        for t in range(10):
            aggregator.add_sample(float(t), ear=0.4, closed_threshold=0.2)
        assert aggregator.perclos == pytest.approx(0.0)

    def test_perclos_one_when_eyes_always_closed(self):
        aggregator = DrowsinessAggregator(window_seconds=60.0)
        for t in range(10):
            aggregator.add_sample(float(t), ear=0.1, closed_threshold=0.2)
        assert aggregator.perclos == pytest.approx(1.0)

    def test_perclos_reflects_partial_closure(self):
        aggregator = DrowsinessAggregator(window_seconds=60.0)
        for t in range(10):
            ear = 0.1 if t < 5 else 0.4  # closed first half, open second half
            aggregator.add_sample(float(t), ear=ear, closed_threshold=0.2)
        assert aggregator.perclos == pytest.approx(0.5)

    def test_old_samples_evicted_outside_window(self):
        aggregator = DrowsinessAggregator(window_seconds=5.0)
        aggregator.add_sample(0.0, ear=0.1, closed_threshold=0.2)  # closed, will age out
        for t in range(1, 11):
            aggregator.add_sample(float(t), ear=0.4, closed_threshold=0.2)  # open
        # t=0 sample is more than 5s behind t=10, so it should no longer count.
        assert aggregator.perclos == pytest.approx(0.0)

    def test_single_blink_counted_once(self):
        aggregator = DrowsinessAggregator(window_seconds=60.0)
        ear_sequence = [0.4, 0.4, 0.1, 0.1, 0.1, 0.4, 0.4, 0.4]
        for t, ear in enumerate(ear_sequence):
            aggregator.add_sample(float(t), ear=ear, closed_threshold=0.2)
        assert aggregator.blink_rate_per_min is not None
        # 3 closed frames >= MIN_BLINK_FRAMES, over a 7s span -> one blink.
        span_s = len(ear_sequence) - 1
        expected_rate = (1 / span_s) * 60.0
        assert aggregator.blink_rate_per_min == pytest.approx(expected_rate)

    def test_single_frame_dip_below_min_blink_frames_not_counted(self):
        assert MIN_BLINK_FRAMES >= 2  # this test assumes a single frame is insufficient
        aggregator = DrowsinessAggregator(window_seconds=60.0)
        ear_sequence = [0.4, 0.4, 0.1, 0.4, 0.4]
        for t, ear in enumerate(ear_sequence):
            aggregator.add_sample(float(t), ear=ear, closed_threshold=0.2)
        assert aggregator.blink_rate_per_min == pytest.approx(0.0)

    def test_two_separate_blinks_counted_separately(self):
        aggregator = DrowsinessAggregator(window_seconds=60.0)
        ear_sequence = [0.4, 0.1, 0.1, 0.4, 0.4, 0.1, 0.1, 0.4]
        for t, ear in enumerate(ear_sequence):
            aggregator.add_sample(float(t), ear=ear, closed_threshold=0.2)
        span_s = len(ear_sequence) - 1
        expected_rate = (2 / span_s) * 60.0
        assert aggregator.blink_rate_per_min == pytest.approx(expected_rate)
