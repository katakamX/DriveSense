import math
from datetime import UTC, datetime, timedelta

from app.core.events.detectors import FrameSample, detect_harsh_braking, detect_rapid_acceleration
from app.core.features.extract import (
    FeatureContext,
    accel_rms,
    accel_std,
    extract_features,
    harsh_braking_per_min,
    rapid_accel_per_min,
    speed_mean,
    speed_std,
)
from app.core.features.schema import FEATURE_NAMES, FeatureSample

T0 = datetime(2026, 1, 1, tzinfo=UTC)


def _sample(
    t_offset_s: float, speed: float = 50.0, accel: float = 0.0, lat_accel: float = 0.0
) -> FeatureSample:
    return FeatureSample(
        recorded_at=T0 + timedelta(seconds=t_offset_s),
        speed_kph=speed,
        accel_ms2=accel,
        lateral_accel_ms2=lat_accel,
    )


def test_speed_mean_and_std_hand_computed() -> None:
    speeds = [10.0, 20.0, 30.0, 40.0]
    samples = [_sample(i, speed=s) for i, s in enumerate(speeds)]

    assert speed_mean(samples) == 25.0
    # population stdev of [10,20,30,40]: mean=25, variance=(15^2+5^2+5^2+15^2)/4=125
    assert speed_std(samples) == math.sqrt(125.0)


def test_accel_rms_hand_computed() -> None:
    accels = [3.0, 4.0]
    samples = [_sample(i, accel=a) for i, a in enumerate(accels)]

    # rms([3,4]) = sqrt((9+16)/2) = sqrt(12.5)
    assert accel_rms(samples) == math.sqrt(12.5)


def test_accel_std_single_sample_is_zero() -> None:
    samples = [_sample(0, accel=5.0)]
    assert accel_std(samples) == 0.0


def test_extract_features_matches_feature_names_length_and_order() -> None:
    samples = [_sample(i, speed=50.0 + i, accel=0.5 * i, lat_accel=0.1 * i) for i in range(20)]
    ctx = FeatureContext(speed_limit_kph=100.0)

    vector = extract_features(samples, ctx)

    assert len(vector.values) == len(FEATURE_NAMES) == 26
    as_dict = vector.as_dict()
    assert set(as_dict.keys()) == set(FEATURE_NAMES)
    # values line up positionally with FEATURE_NAMES
    for name, value in zip(FEATURE_NAMES, vector.values, strict=True):
        assert as_dict[name] == value


def test_extract_features_window_bounds_and_sample_count() -> None:
    samples = [_sample(i) for i in range(10)]
    ctx = FeatureContext(speed_limit_kph=100.0, coverage_ratio=0.75)

    vector = extract_features(samples, ctx)

    assert vector.sample_count == 10
    assert vector.window_start == T0
    assert vector.window_end == T0 + timedelta(seconds=9)
    assert vector.coverage_ratio == 0.75


def test_harsh_braking_per_min_reuses_events_detector_not_a_reimplementation() -> None:
    # accel values straddling HARSH_BRAKING_ACCEL_MS2 = -3.5
    accels = [0.0, -4.0, -1.0, -5.0, 0.0, -3.6, 2.0]
    samples = [_sample(i, accel=a) for i, a in enumerate(accels)]
    duration_min = (len(accels) - 1) / 60.0  # 6 seconds of 1s-spaced samples

    frame_samples = [
        FrameSample(
            telemetry_id=i, recorded_at=s.recorded_at, accel_ms2=s.accel_ms2, speed_kph=s.speed_kph
        )
        for i, s in enumerate(samples)
    ]
    direct_events = detect_harsh_braking(frame_samples)

    assert harsh_braking_per_min(samples) == len(direct_events) / duration_min


def test_rapid_accel_per_min_reuses_events_detector_not_a_reimplementation() -> None:
    # accel values straddling RAPID_ACCELERATION_ACCEL_MS2 = 3.0
    accels = [0.0, 3.5, 1.0, 4.0, 0.0, 3.0, -2.0]
    samples = [_sample(i, accel=a) for i, a in enumerate(accels)]
    duration_min = (len(accels) - 1) / 60.0

    frame_samples = [
        FrameSample(
            telemetry_id=i, recorded_at=s.recorded_at, accel_ms2=s.accel_ms2, speed_kph=s.speed_kph
        )
        for i, s in enumerate(samples)
    ]
    direct_events = detect_rapid_acceleration(frame_samples)

    assert rapid_accel_per_min(samples) == len(direct_events) / duration_min


def test_speeding_time_ratio_uses_speed_limit_from_context() -> None:
    from app.core.features.extract import speeding_time_ratio

    speeds = [50.0, 120.0, 60.0, 130.0]  # limit 100 + margin 5 -> threshold 105
    samples = [_sample(i, speed=s) for i, s in enumerate(speeds)]
    ctx = FeatureContext(speed_limit_kph=100.0)

    assert speeding_time_ratio(samples, ctx) == 2 / 4
