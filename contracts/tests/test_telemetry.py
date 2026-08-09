from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from drivesense_contracts import (
    SCHEMA_VERSION,
    TelemetryFrame,
    TripMeta,
    gear_label,
)

BASE_FRAME = {
    "trip_id": "t-1",
    "source": "simulator",
    "seq": 0,
    "sim_t": 0.0,
    "ts": datetime(2026, 1, 1, tzinfo=UTC),
    "speed_kph": 0.0,
    "accel_ms2": 0.0,
    "engine_rpm": 800.0,
    "throttle_pct": 0.0,
    "brake_pct": 0.0,
    "clutch_pct": 0.0,
    "gear": 0,
    "engine_load_pct": 0.0,
    "steering_deg": 0.0,
    "yaw_rate_dps": 0.0,
    "lateral_accel_ms2": 0.0,
    "heading_deg": 0.0,
    "distance_m": 0.0,
}


def test_minimal_frame_validates_and_defaults_optionals_to_none() -> None:
    frame = TelemetryFrame(**BASE_FRAME)

    assert frame.schema_version == SCHEMA_VERSION
    # Unsupported PIDs must be absent, never a fabricated zero.
    assert frame.lat is None
    assert frame.lon is None
    assert frame.coolant_c is None


def test_frame_is_immutable() -> None:
    frame = TelemetryFrame(**BASE_FRAME)

    with pytest.raises(ValidationError):
        frame.speed_kph = 10.0  # type: ignore[misc]


def test_unknown_field_is_rejected() -> None:
    with pytest.raises(ValidationError):
        TelemetryFrame(**BASE_FRAME, boost_psi=12.0)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("throttle_pct", 101.0),
        ("brake_pct", -1.0),
        ("clutch_pct", 150.0),
        ("engine_rpm", -1.0),
        ("gear", -2),
        ("seq", -1),
        ("heading_deg", 360.0),
        ("lat", 91.0),
    ],
)
def test_out_of_range_values_are_rejected(field: str, value: float) -> None:
    with pytest.raises(ValidationError):
        TelemetryFrame(**{**BASE_FRAME, field: value})


def test_json_round_trip_preserves_values() -> None:
    frame = TelemetryFrame(**{**BASE_FRAME, "lat": 12.9716, "lon": 77.5946, "coolant_c": 88.5})

    restored = TelemetryFrame.model_validate_json(frame.model_dump_json())

    assert restored == frame


@pytest.mark.parametrize(("gear", "expected"), [(-1, "R"), (0, "N"), (1, "1"), (6, "6")])
def test_gear_label(gear: int, expected: str) -> None:
    assert gear_label(gear) == expected
    assert TelemetryFrame(**{**BASE_FRAME, "gear": gear}).gear_label == expected


def test_trip_meta_round_trip() -> None:
    meta = TripMeta(
        trip_id="t-1",
        source="simulator",
        started_at=datetime(2026, 1, 1, tzinfo=UTC),
        sample_rate_hz=10.0,
        generator="drivesense-sim",
        generator_version="0.1.0",
        vehicle={"name": "hatchback"},
    )

    assert TripMeta.model_validate_json(meta.model_dump_json()) == meta
