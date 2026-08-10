"""The 26 core features and their reduction into a FeatureVector.

Features 23, 24 and 26 (harsh-braking rate, rapid-acceleration rate, and the
combined event rate) call straight into `app.core.events.detectors` rather
than reimplementing the thresholds — that module is the one place
"harsh braking" is defined (see app/core/events/thresholds.py), and this
module must not grow a second, silently divergent definition of it.
"""

import math
from collections.abc import Callable
from dataclasses import dataclass

from app.core.events.detectors import (
    FrameSample,
    detect_events,
    detect_harsh_braking,
    detect_rapid_acceleration,
)
from app.core.features import stats
from app.core.features.schema import FEATURE_NAMES, FEATURE_VERSION, FeatureSample, FeatureVector


@dataclass(frozen=True)
class FeatureContext:
    """Whatever extraction needs beyond the samples themselves."""

    speed_limit_kph: float
    coverage_ratio: float = 1.0


def _sorted_by_time(samples: list[FeatureSample]) -> list[FeatureSample]:
    return sorted(samples, key=lambda s: s.recorded_at)


def _speeds(samples: list[FeatureSample]) -> list[float]:
    return [s.speed_kph for s in samples]


def _accels(samples: list[FeatureSample]) -> list[float]:
    return [s.accel_ms2 for s in samples]


def _lat_accels(samples: list[FeatureSample]) -> list[float]:
    return [s.lateral_accel_ms2 for s in samples]


def _jerk_series(samples: list[FeatureSample]) -> list[float]:
    ordered = _sorted_by_time(samples)
    jerks = []
    for prev, cur in zip(ordered, ordered[1:], strict=False):
        dt = (cur.recorded_at - prev.recorded_at).total_seconds()
        if dt > 0:
            jerks.append((cur.accel_ms2 - prev.accel_ms2) / dt)
    return jerks


def _angle_diff_deg(a: float, b: float) -> float:
    """Shortest signed difference b - a, wrapped into (-180, 180]."""
    return (b - a + 180.0) % 360.0 - 180.0


def _duration_minutes(samples: list[FeatureSample]) -> float:
    ordered = _sorted_by_time(samples)
    if len(ordered) < 2:
        return 0.0
    span_s = (ordered[-1].recorded_at - ordered[0].recorded_at).total_seconds()
    return span_s / 60.0 if span_s > 0 else 0.0


def _as_frame_samples(samples: list[FeatureSample]) -> list[FrameSample]:
    return [
        FrameSample(
            telemetry_id=i,
            recorded_at=s.recorded_at,
            accel_ms2=s.accel_ms2,
            speed_kph=s.speed_kph,
        )
        for i, s in enumerate(_sorted_by_time(samples))
    ]


# --- Speed ---------------------------------------------------------------


def speed_mean(samples: list[FeatureSample]) -> float:
    return stats.mean(_speeds(samples))


def speed_std(samples: list[FeatureSample]) -> float:
    return stats.std(_speeds(samples))


def speed_max(samples: list[FeatureSample]) -> float:
    return stats.maximum(_speeds(samples))


def speed_cv(samples: list[FeatureSample]) -> float:
    m = speed_mean(samples)
    return speed_std(samples) / m if m != 0 else 0.0


def speed_range(samples: list[FeatureSample]) -> float:
    speeds = _speeds(samples)
    return stats.maximum(speeds) - stats.minimum(speeds) if speeds else 0.0


def stop_ratio(samples: list[FeatureSample]) -> float:
    return stats.time_below_threshold(_speeds(samples), 3.0)


# --- Longitudinal acceleration --------------------------------------------


def accel_mean_abs(samples: list[FeatureSample]) -> float:
    return stats.mean([abs(a) for a in _accels(samples)])


def accel_std(samples: list[FeatureSample]) -> float:
    return stats.std(_accels(samples))


def accel_max(samples: list[FeatureSample]) -> float:
    return stats.maximum(_accels(samples))


def accel_min(samples: list[FeatureSample]) -> float:
    return stats.minimum(_accels(samples))


def accel_rms(samples: list[FeatureSample]) -> float:
    return stats.rms(_accels(samples))


def accel_time_ratio(samples: list[FeatureSample]) -> float:
    return stats.time_above_threshold(_accels(samples), 0.5)


def brake_time_ratio(samples: list[FeatureSample]) -> float:
    return stats.time_below_threshold(_accels(samples), -0.5)


# --- Jerk (smoothness) -----------------------------------------------------


def jerk_std(samples: list[FeatureSample]) -> float:
    return stats.std(_jerk_series(samples))


def jerk_max_abs(samples: list[FeatureSample]) -> float:
    jerks = _jerk_series(samples)
    return max(abs(j) for j in jerks) if jerks else 0.0


# --- Lateral -----------------------------------------------------------


def lat_accel_std(samples: list[FeatureSample]) -> float:
    return stats.std(_lat_accels(samples))


def lat_accel_max_abs(samples: list[FeatureSample]) -> float:
    lat_accels = _lat_accels(samples)
    return max(abs(a) for a in lat_accels) if lat_accels else 0.0


def lat_accel_time_ratio(samples: list[FeatureSample]) -> float:
    return stats.time_above_threshold([abs(a) for a in _lat_accels(samples)], 2.5)


def accel_magnitude_mean(samples: list[FeatureSample]) -> float:
    magnitudes = [math.hypot(s.accel_ms2, s.lateral_accel_ms2) for s in samples]
    return stats.mean(magnitudes)


def accel_magnitude_max(samples: list[FeatureSample]) -> float:
    magnitudes = [math.hypot(s.accel_ms2, s.lateral_accel_ms2) for s in samples]
    return stats.maximum(magnitudes)


# --- Heading / yaw -----------------------------------------------------


def yaw_rate_std(samples: list[FeatureSample]) -> float:
    yaw_rates = [s.yaw_rate_dps for s in samples if s.yaw_rate_dps is not None]
    return stats.std(yaw_rates)


def heading_change_rate(samples: list[FeatureSample]) -> float:
    ordered = [s for s in _sorted_by_time(samples) if s.heading_deg is not None]
    rates = []
    for prev, cur in zip(ordered, ordered[1:], strict=False):
        dt = (cur.recorded_at - prev.recorded_at).total_seconds()
        if dt > 0:
            assert prev.heading_deg is not None and cur.heading_deg is not None
            rates.append(abs(_angle_diff_deg(prev.heading_deg, cur.heading_deg)) / dt)
    return stats.mean(rates)


# --- Events (reuse core.events detectors; do not reimplement thresholds) --


def harsh_braking_per_min(samples: list[FeatureSample]) -> float:
    duration_min = _duration_minutes(samples)
    if duration_min <= 0:
        return 0.0
    events = detect_harsh_braking(_as_frame_samples(samples))
    return len(events) / duration_min


def rapid_accel_per_min(samples: list[FeatureSample]) -> float:
    duration_min = _duration_minutes(samples)
    if duration_min <= 0:
        return 0.0
    events = detect_rapid_acceleration(_as_frame_samples(samples))
    return len(events) / duration_min


def speeding_time_ratio(samples: list[FeatureSample], ctx: FeatureContext) -> float:
    if not samples:
        return 0.0
    events = detect_events(_as_frame_samples(samples), ctx.speed_limit_kph)
    speeding_count = sum(1 for e in events if e.event_type == "speeding")
    return speeding_count / len(samples)


def event_rate_per_min(samples: list[FeatureSample], ctx: FeatureContext) -> float:
    duration_min = _duration_minutes(samples)
    if duration_min <= 0:
        return 0.0
    events = detect_events(_as_frame_samples(samples), ctx.speed_limit_kph)
    return len(events) / duration_min


# --- Assembly ---------------------------------------------------------------

_SIMPLE_FEATURES: tuple[Callable[[list[FeatureSample]], float], ...] = (
    speed_mean,
    speed_std,
    speed_max,
    speed_cv,
    speed_range,
    stop_ratio,
    accel_mean_abs,
    accel_std,
    accel_max,
    accel_min,
    accel_rms,
    accel_time_ratio,
    brake_time_ratio,
    jerk_std,
    jerk_max_abs,
    lat_accel_std,
    lat_accel_max_abs,
    lat_accel_time_ratio,
    accel_magnitude_mean,
    accel_magnitude_max,
    yaw_rate_std,
    heading_change_rate,
    harsh_braking_per_min,
    rapid_accel_per_min,
)


def extract_features(samples: list[FeatureSample], ctx: FeatureContext) -> FeatureVector:
    """Reduce one window's samples to a FeatureVector, values ordered per FEATURE_NAMES."""
    if not samples:
        raise ValueError("extract_features requires at least one sample")

    ordered = _sorted_by_time(samples)
    values: dict[str, float] = {fn.__name__: fn(ordered) for fn in _SIMPLE_FEATURES}
    values["speeding_time_ratio"] = speeding_time_ratio(ordered, ctx)
    values["event_rate_per_min"] = event_rate_per_min(ordered, ctx)

    return FeatureVector(
        window_start=ordered[0].recorded_at,
        window_end=ordered[-1].recorded_at,
        sample_count=len(ordered),
        coverage_ratio=ctx.coverage_ratio,
        feature_version=FEATURE_VERSION,
        values=tuple(values[name] for name in FEATURE_NAMES),
    )
