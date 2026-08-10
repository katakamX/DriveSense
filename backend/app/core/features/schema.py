"""Shared feature schema — the single vocabulary both training and inference speak.

`FeatureSample` is deliberately narrower than `TelemetryFrame`: it is the
subset every producer (simulator, OBD2, and offline datasets like
UAH-DriveSet) can populate. Extended fields are optional because most
producers cannot supply them; the 26 core features never read them. See
docs/adr/0004-shared-feature-engineering.md.
"""

from dataclasses import dataclass
from datetime import datetime

FEATURE_VERSION = "1"

FEATURE_NAMES: tuple[str, ...] = (
    "speed_mean",
    "speed_std",
    "speed_max",
    "speed_cv",
    "speed_range",
    "stop_ratio",
    "accel_mean_abs",
    "accel_std",
    "accel_max",
    "accel_min",
    "accel_rms",
    "accel_time_ratio",
    "brake_time_ratio",
    "jerk_std",
    "jerk_max_abs",
    "lat_accel_std",
    "lat_accel_max_abs",
    "lat_accel_time_ratio",
    "accel_magnitude_mean",
    "accel_magnitude_max",
    "yaw_rate_std",
    "heading_change_rate",
    "harsh_braking_per_min",
    "rapid_accel_per_min",
    "speeding_time_ratio",
    "event_rate_per_min",
)

# Named but not computed: no UAH-DriveSet counterpart, so these would break
# external validation the moment they entered the model. Adding one to
# FEATURE_NAMES is a deliberate, visible act — not a side effect of this list.
EXTENDED_FEATURES: tuple[str, ...] = (
    "throttle_mean",
    "throttle_std",
    "brake_application_count",
    "gear_change_rate",
    "rpm_mean",
    "rpm_max",
    "engine_load_mean",
    "clutch_time_ratio",
)


@dataclass(frozen=True)
class FeatureSample:
    """The subset of a telemetry frame feature extraction needs.

    Producer-agnostic: populated from a live `TelemetryFrame`, a simulator
    JSONL recording, or a parsed UAH-DriveSet row. Optional fields are
    genuinely optional — a producer that cannot supply one must pass `None`
    rather than a fabricated value.
    """

    recorded_at: datetime
    speed_kph: float
    accel_ms2: float
    lateral_accel_ms2: float
    yaw_rate_dps: float | None = None
    heading_deg: float | None = None
    lat: float | None = None
    lon: float | None = None

    # Extended / optional — unused by the 26 core features today.
    throttle_pct: float | None = None
    brake_pct: float | None = None
    gear: int | None = None
    engine_rpm: float | None = None
    engine_load_pct: float | None = None
    clutch_pct: float | None = None


@dataclass(frozen=True)
class FeatureVector:
    """One labelled-or-labellable row: a window's worth of samples reduced to numbers."""

    window_start: datetime
    window_end: datetime
    sample_count: int
    coverage_ratio: float
    feature_version: str
    values: tuple[float, ...]  # aligned 1:1 with FEATURE_NAMES

    def as_dict(self) -> dict[str, float]:
        return dict(zip(FEATURE_NAMES, self.values, strict=True))
