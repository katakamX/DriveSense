"""UAH-DriveSet adapter tests.

The axis-validation tests are parametrised over every recording directory
discovered under the fixtures tree *and* under `data/raw/uah-driveset` when
the real dataset is present. Dropping new recordings in either location adds
them to this suite automatically — the axis convention keeps being checked
against data rather than asserted once.
"""

from __future__ import annotations

import logging
import math
from datetime import datetime
from pathlib import Path

import pytest

from pipelines.adapters.uah import (
    G_TO_MS2,
    AxisMapping,
    UahParseError,
    build_samples,
    detect_axis_mapping,
    find_recordings,
    load_recording,
    parse_accelerometer_file,
    parse_gps_file,
    parse_recording_name,
    wrap_degrees,
    yaw_rates_dps,
)

FIXTURES = Path(__file__).parent / "fixtures" / "uah_sample"
CLEAN = FIXTURES / "20151110175712-16km-D1-NORMAL-MOTORWAY"
MALFORMED = FIXTURES / "20151110180000-5km-D2-AGGRESSIVE-SECONDARY"
REAL_DATA = Path(__file__).resolve().parents[2] / "data" / "raw" / "uah-driveset"


def _all_recordings() -> list[Path]:
    return find_recordings(FIXTURES) + find_recordings(REAL_DATA)


# --- Directory naming -----------------------------------------------------


def test_parse_recording_name_recovers_driver_labels_and_start_instant() -> None:
    meta = parse_recording_name("20151110175712-16km-D1-NORMAL-MOTORWAY")

    assert meta.driver_id == "D1"
    assert meta.behaviour == "NORMAL"
    assert meta.road_type == "MOTORWAY"
    assert meta.distance_km == 16.0
    assert meta.started_at == datetime(2015, 11, 10, 17, 57, 12)


def test_parse_recording_name_rejects_unrecognised_directory() -> None:
    with pytest.raises(UahParseError):
        parse_recording_name("some-random-folder")


# --- Angle handling -------------------------------------------------------


@pytest.mark.parametrize(
    ("delta", "expected"),
    [(9.0, 9.0), (-9.0, -9.0), (351.0, -9.0), (-351.0, 9.0), (360.0, 0.0)],
)
def test_wrap_degrees(delta: float, expected: float) -> None:
    assert wrap_degrees(delta) == pytest.approx(expected)


def test_yaw_rate_handles_the_180_degree_wraparound() -> None:
    rows, _ = parse_accelerometer_file(CLEAN / "RAW_ACCELEROMETERS.txt")
    rates = yaw_rates_dps(rows)

    # The fixture crosses +/-180 during the turning phase at a bounded rate.
    # Without wraparound handling the crossing produces a ~3600 deg/s spike.
    assert rates, "expected yaw rates to be derived"
    assert max(abs(rate) for _, rate in rates) < 20.0

    crossing = [rate for t, rate in rates if 12.5 <= t <= 13.5]
    assert crossing
    assert all(0.0 < rate < 20.0 for rate in crossing)


# --- Unit conversion ------------------------------------------------------


def test_g_to_ms2_conversion_uses_standard_gravity() -> None:
    accel_rows, _ = parse_accelerometer_file(CLEAN / "RAW_ACCELEROMETERS.txt")
    gps_rows, _ = parse_gps_file(CLEAN / "RAW_GPS.txt")
    mapping = AxisMapping(longitudinal="Z", longitudinal_sign=1.0, lateral="Y", lateral_sign=1.0)

    samples = build_samples(accel_rows, gps_rows, mapping)

    first_accel = accel_rows[0]
    assert samples[0].accel_ms2 == pytest.approx(first_accel.z_g * 9.80665)
    assert samples[0].lateral_accel_ms2 == pytest.approx(first_accel.y_g * 9.80665)
    assert G_TO_MS2 == 9.80665


def test_adapter_reads_raw_channels_not_kalman_filtered_ones() -> None:
    # The fixture's KF columns carry the same signal with the jitter removed,
    # so a value matching raw-but-not-KF proves which columns were read.
    accel_rows, _ = parse_accelerometer_file(CLEAN / "RAW_ACCELEROMETERS.txt")
    gps_rows, _ = parse_gps_file(CLEAN / "RAW_GPS.txt")
    mapping = AxisMapping(longitudinal="Z", longitudinal_sign=1.0, lateral="Y", lateral_sign=1.0)

    samples = build_samples(accel_rows, gps_rows, mapping)

    # Row 1 is the first whose raw Z differs from its KF Z in the fixture.
    kf_longitudinal = 0.101972 * G_TO_MS2  # Z_KF for row 1
    assert samples[1].accel_ms2 != pytest.approx(kf_longitudinal, abs=1e-6)
    assert samples[1].accel_ms2 == pytest.approx(accel_rows[1].z_g * G_TO_MS2)


# --- Forward-fill ---------------------------------------------------------


def test_gps_speed_is_forward_filled_never_interpolated() -> None:
    accel_rows, _ = parse_accelerometer_file(CLEAN / "RAW_ACCELEROMETERS.txt")
    gps_rows, _ = parse_gps_file(CLEAN / "RAW_GPS.txt")
    mapping = AxisMapping(longitudinal="Z", longitudinal_sign=1.0, lateral="Y", lateral_sign=1.0)

    samples = build_samples(accel_rows, gps_rows, mapping)

    # GPS is 1 Hz, accelerometers 10 Hz: the ten samples inside one GPS second
    # must all carry that fix's speed exactly, with no intermediate values.
    first_second = [s for s in samples if s.recorded_at.microsecond < 1_000_000][:10]
    assert len(first_second) == 10
    assert {s.speed_kph for s in first_second} == {gps_rows[0].speed_kph}

    # Every emitted speed must be a value that actually appears in the GPS file.
    observed_speeds = {round(s.speed_kph, 6) for s in samples}
    gps_speeds = {round(r.speed_kph, 6) for r in gps_rows}
    assert observed_speeds <= gps_speeds


def test_samples_before_the_first_gps_fix_are_dropped_not_backfilled() -> None:
    accel_rows, _ = parse_accelerometer_file(CLEAN / "RAW_ACCELEROMETERS.txt")
    gps_rows, _ = parse_gps_file(CLEAN / "RAW_GPS.txt")
    mapping = AxisMapping(longitudinal="Z", longitudinal_sign=1.0, lateral="Y", lateral_sign=1.0)

    late_fixes = [r for r in gps_rows if r.t >= 5.0]
    samples = build_samples(accel_rows, late_fixes, mapping)

    expected = len([r for r in accel_rows if r.t >= 5.0])
    assert len(samples) == expected
    assert all(s.speed_kph in {r.speed_kph for r in late_fixes} for s in samples)


# --- Malformed input ------------------------------------------------------


def test_malformed_accelerometer_rows_are_skipped_and_logged(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.WARNING):
        rows, skipped = parse_accelerometer_file(MALFORMED / "RAW_ACCELEROMETERS.txt")

    assert skipped == 2  # one truncated row, one non-numeric field
    assert len(rows) == 4
    assert any("skipped 2 malformed row" in record.getMessage() for record in caplog.records)


def test_malformed_gps_rows_are_skipped_and_logged(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING):
        rows, skipped = parse_gps_file(MALFORMED / "RAW_GPS.txt")

    assert skipped == 1
    assert len(rows) == 2


def test_a_malformed_recording_still_loads_the_rest() -> None:
    accel_rows, skipped_accel = parse_accelerometer_file(MALFORMED / "RAW_ACCELEROMETERS.txt")
    gps_rows, skipped_gps = parse_gps_file(MALFORMED / "RAW_GPS.txt")
    mapping = AxisMapping(longitudinal="Z", longitudinal_sign=1.0, lateral="Y", lateral_sign=1.0)

    samples = build_samples(accel_rows, gps_rows, mapping)

    assert skipped_accel + skipped_gps == 3
    assert samples, "surviving rows must still produce samples"


def test_comment_and_blank_lines_are_ignored() -> None:
    rows, skipped = parse_accelerometer_file(CLEAN / "RAW_ACCELEROMETERS.txt")

    assert skipped == 0  # the four synthetic-fixture header comments are not errors
    assert len(rows) == 200


# --- Axis validation, run against every available recording ---------------


@pytest.mark.parametrize("recording", _all_recordings(), ids=lambda p: p.name)
def test_axis_detection_identifies_distinct_longitudinal_and_lateral_channels(
    recording: Path,
) -> None:
    accel_rows, _ = parse_accelerometer_file(recording / "RAW_ACCELEROMETERS.txt")
    gps_rows, _ = parse_gps_file(recording / "RAW_GPS.txt")

    try:
        detection = detect_axis_mapping(accel_rows, gps_rows)
    except UahParseError as exc:
        pytest.skip(f"{recording.name}: insufficient data to detect axes ({exc})")

    assert detection.mapping.longitudinal != detection.mapping.lateral
    assert detection.longitudinal_strength >= 0.5
    assert detection.lateral_strength >= 0.5


def test_axis_detection_recovers_the_fixtures_known_ground_truth() -> None:
    # The clean fixture is built with Z carrying d(speed)/dt and Y carrying
    # speed*yaw_rate. Detection must find that from the numbers alone.
    accel_rows, _ = parse_accelerometer_file(CLEAN / "RAW_ACCELEROMETERS.txt")
    gps_rows, _ = parse_gps_file(CLEAN / "RAW_GPS.txt")

    detection = detect_axis_mapping(accel_rows, gps_rows)

    assert detection.mapping.longitudinal == "Z"
    assert detection.mapping.lateral == "Y"
    assert detection.mapping.longitudinal_sign == 1.0
    assert detection.mapping.lateral_sign == 1.0
    assert detection.longitudinal_strength > 0.9
    assert detection.lateral_strength > 0.9
    # X is the decoy channel and must not win either axis.
    assert abs(detection.longitudinal_correlations["X"]) < 0.5
    assert abs(detection.lateral_correlations["X"]) < 0.5


def test_axis_detection_recovers_an_inverted_mounting() -> None:
    accel_rows, _ = parse_accelerometer_file(CLEAN / "RAW_ACCELEROMETERS.txt")
    gps_rows, _ = parse_gps_file(CLEAN / "RAW_GPS.txt")
    flipped = [
        type(row)(
            t=row.t,
            activation=row.activation,
            x_g=row.x_g,
            y_g=row.y_g,
            z_g=-row.z_g,
            yaw_deg=row.yaw_deg,
        )
        for row in accel_rows
    ]

    detection = detect_axis_mapping(flipped, gps_rows)

    assert detection.mapping.longitudinal == "Z"
    assert detection.mapping.longitudinal_sign == -1.0


def test_axis_detection_refuses_when_no_straight_driving_exists() -> None:
    # Only the turning half of the fixture: every interval is cornering, so
    # the longitudinal channel cannot be identified and guessing is refused.
    accel_rows, _ = parse_accelerometer_file(CLEAN / "RAW_ACCELEROMETERS.txt")
    gps_rows, _ = parse_gps_file(CLEAN / "RAW_GPS.txt")
    turning_accel = [r for r in accel_rows if r.t >= 10.0]
    turning_gps = [r for r in gps_rows if r.t >= 10.0]

    with pytest.raises(UahParseError, match="near-straight"):
        detect_axis_mapping(turning_accel, turning_gps)


# --- End-to-end -----------------------------------------------------------


def test_load_recording_produces_rebased_timestamps_and_metadata() -> None:
    recording = load_recording(CLEAN)

    assert recording.meta.driver_id == "D1"
    assert recording.meta.road_type == "MOTORWAY"
    assert recording.meta.behaviour == "NORMAL"
    assert recording.skipped_accel_rows == 0
    assert recording.skipped_gps_rows == 0

    # Timestamps are seconds-since-start rebased onto the folder-name instant.
    assert recording.samples[0].recorded_at == datetime(2015, 11, 10, 17, 57, 12)
    span = (recording.samples[-1].recorded_at - recording.samples[0].recorded_at).total_seconds()
    assert span == pytest.approx(19.9, abs=0.05)


def test_load_recording_populates_every_core_feature_input() -> None:
    recording = load_recording(CLEAN)
    sample = recording.samples[50]

    assert sample.speed_kph >= 0.0
    assert math.isfinite(sample.accel_ms2)
    assert math.isfinite(sample.lateral_accel_ms2)
    assert sample.yaw_rate_dps is not None
    assert sample.heading_deg is not None and 0.0 <= sample.heading_deg < 360.0
    assert sample.lat is not None and sample.lon is not None
    # Extended fields have no UAH counterpart and must stay absent, not zeroed.
    assert sample.throttle_pct is None
    assert sample.gear is None


def test_load_recording_rejects_a_directory_without_the_raw_files(tmp_path: Path) -> None:
    empty = tmp_path / "20151110175712-16km-D3-DROWSY-SECONDARY"
    empty.mkdir()

    with pytest.raises(UahParseError, match="not found"):
        load_recording(empty)
