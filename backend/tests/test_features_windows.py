from datetime import UTC, datetime, timedelta

from app.core.features.schema import FeatureSample
from app.core.features.windows import make_windows

T0 = datetime(2026, 1, 1, tzinfo=UTC)


def _sample(t_offset_s: float) -> FeatureSample:
    return FeatureSample(
        recorded_at=T0 + timedelta(seconds=t_offset_s),
        speed_kph=50.0,
        accel_ms2=0.0,
        lateral_accel_ms2=0.0,
    )


def test_span_and_overlap_on_evenly_spaced_input() -> None:
    # 1 Hz for 61 seconds -> samples at t=0..60
    samples = [_sample(i) for i in range(61)]

    windows = make_windows(samples, span_s=30.0, overlap=0.5, expected_rate_hz=1.0)

    # starts advance by stride = span * (1 - overlap) = 15s, while start <= t_last(=60)
    expected_starts = [T0 + timedelta(seconds=s) for s in (0, 15, 30, 45, 60)]
    assert [w.window_start for w in windows] == expected_starts
    assert len(windows) == 5

    # fully covered windows contain exactly 30 samples (half-open [start, start+30))
    assert windows[0].sample_count == 30
    assert windows[1].sample_count == 30
    assert windows[2].sample_count == 30
    assert windows[0].coverage_ratio == 1.0

    # tail windows are partially covered
    assert windows[3].sample_count == 16  # t=45..60 inclusive
    assert windows[3].coverage_ratio == 16 / 30
    assert windows[4].sample_count == 1  # only t=60
    assert windows[4].coverage_ratio == 1 / 30


def test_exact_boundary_sample_belongs_to_later_window() -> None:
    # windows are half-open [start, end): a sample exactly at t=30 must fall
    # into the [30, 60) window, not [0, 30).
    samples = [_sample(0), _sample(30)]

    windows = make_windows(samples, span_s=30.0, overlap=0.5, expected_rate_hz=1.0)

    first_window = next(w for w in windows if w.window_start == T0)
    later_window = next(w for w in windows if w.window_start == T0 + timedelta(seconds=30))

    assert first_window.samples == (samples[0],)
    assert samples[1] in later_window.samples


def test_coverage_ratio_reflects_gappy_input() -> None:
    # Nominal rate is 1 Hz but only every other sample is present -> half coverage.
    samples = [_sample(i) for i in range(0, 30, 2)]  # t = 0, 2, 4, ..., 28 -> 15 samples

    windows = make_windows(samples, span_s=30.0, overlap=0.5, expected_rate_hz=1.0)

    assert windows[0].sample_count == 15
    assert windows[0].coverage_ratio == 15 / 30


def test_fewer_samples_than_one_window_yields_single_partial_window() -> None:
    samples = [_sample(i) for i in range(5)]  # t = 0..4, far shorter than a 30s span

    windows = make_windows(samples, span_s=30.0, overlap=0.5, expected_rate_hz=1.0)

    assert len(windows) == 1
    assert windows[0].sample_count == 5
    assert windows[0].coverage_ratio == 5 / 30


def test_empty_input_yields_no_windows() -> None:
    assert make_windows([], span_s=30.0, overlap=0.5, expected_rate_hz=1.0) == []


def test_invalid_span_and_overlap_raise() -> None:
    import pytest

    samples = [_sample(0)]
    with pytest.raises(ValueError):
        make_windows(samples, span_s=0.0, overlap=0.5, expected_rate_hz=1.0)
    with pytest.raises(ValueError):
        make_windows(samples, span_s=30.0, overlap=1.0, expected_rate_hz=1.0)
