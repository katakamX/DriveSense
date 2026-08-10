"""Pure, deterministic driving-event detectors.

No DB access here — these take plain data in and return plain data out. The
caller is responsible for turning the result into persisted rows.
"""

from dataclasses import dataclass
from datetime import datetime

from app.core.events.thresholds import (
    HARSH_BRAKING_ACCEL_MS2,
    RAPID_ACCELERATION_ACCEL_MS2,
    SPEEDING_MARGIN_KPH,
)


@dataclass(frozen=True)
class FrameSample:
    """The subset of a telemetry frame detectors need, keyed to its stored row."""

    telemetry_id: int
    recorded_at: datetime
    accel_ms2: float
    speed_kph: float


@dataclass(frozen=True)
class DetectedEvent:
    telemetry_id: int
    recorded_at: datetime
    event_type: str
    measured_value: float
    threshold_value: float


def detect_harsh_braking(frames: list[FrameSample]) -> list[DetectedEvent]:
    return [
        DetectedEvent(
            f.telemetry_id, f.recorded_at, "harsh_braking", f.accel_ms2, HARSH_BRAKING_ACCEL_MS2
        )
        for f in frames
        if f.accel_ms2 <= HARSH_BRAKING_ACCEL_MS2
    ]


def detect_rapid_acceleration(frames: list[FrameSample]) -> list[DetectedEvent]:
    return [
        DetectedEvent(
            f.telemetry_id,
            f.recorded_at,
            "rapid_acceleration",
            f.accel_ms2,
            RAPID_ACCELERATION_ACCEL_MS2,
        )
        for f in frames
        if f.accel_ms2 >= RAPID_ACCELERATION_ACCEL_MS2
    ]


def detect_speeding(frames: list[FrameSample], speed_limit_kph: float) -> list[DetectedEvent]:
    threshold = speed_limit_kph + SPEEDING_MARGIN_KPH
    return [
        DetectedEvent(f.telemetry_id, f.recorded_at, "speeding", f.speed_kph, threshold)
        for f in frames
        if f.speed_kph > threshold
    ]


def detect_events(frames: list[FrameSample], speed_limit_kph: float) -> list[DetectedEvent]:
    return [
        *detect_harsh_braking(frames),
        *detect_rapid_acceleration(frames),
        *detect_speeding(frames, speed_limit_kph),
    ]
