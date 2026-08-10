"""UAH-DriveSet -> FeatureSample adapter.

Parses a single UAH-DriveSet recording directory (``RAW_ACCELEROMETERS.txt``
and ``RAW_GPS.txt``) into the shared ``FeatureSample`` sequence that
``app.core.features`` consumes. Everything dataset-specific — units, axis
convention, resampling, file layout — is confined here; the shared feature
module never learns what UAH is (ADR 0004).

Column layout confirmed against the dataset author's own reader tool
(Eromera/uah_driveset_reader).

Two decisions are recorded here because they change the numbers downstream:

*Raw, not Kalman-filtered, accelerometer channels.* The KF columns (5-7) are
smoother and are what the dataset's own analysis uses, but the smoothing
suppresses exactly the high-frequency content that features 14, 15 and 20
(``jerk_std``, ``jerk_max_abs``, ``accel_magnitude_max``) exist to measure.
Deliberate choice; belongs in the model card.

*Forward-fill, never interpolate.* GPS is 1 Hz and accelerometers are 10 Hz.
Each accelerometer sample takes the speed/course of the most recent GPS
fix at or before it. Accelerometer samples preceding the first GPS fix are
dropped rather than back-filled — a speed we do not have must not be
invented (see the contracts package's stance on absent values).
"""

from __future__ import annotations

import logging
import math
import re
import statistics
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from app.core.features import FeatureSample

logger = logging.getLogger(__name__)

# --- Constants ------------------------------------------------------------

G_TO_MS2 = 9.80665

ACCEL_FILENAME = "RAW_ACCELEROMETERS.txt"
GPS_FILENAME = "RAW_GPS.txt"

# RAW_ACCELEROMETERS column indices.
ACC_TIMESTAMP = 0
ACC_ACTIVATION = 1
ACC_X_G = 2
ACC_Y_G = 3
ACC_Z_G = 4
ACC_X_KF = 5
ACC_Y_KF = 6
ACC_Z_KF = 7
ACC_ROLL = 8
ACC_PITCH = 9
ACC_YAW = 10
ACC_MIN_COLUMNS = 11

# RAW_GPS column indices. Columns 9-11 are internal and deliberately ignored.
GPS_TIMESTAMP = 0
GPS_SPEED_KPH = 1
GPS_LATITUDE = 2
GPS_LONGITUDE = 3
GPS_ALTITUDE = 4
GPS_VERTICAL_ACCURACY = 5
GPS_HORIZONTAL_ACCURACY = 6
GPS_COURSE = 7
GPS_DIFCOURSE = 8
GPS_MIN_COLUMNS = 9

CHANNELS = ("X", "Y", "Z")

# Recording directory names look like 20151110175712-16km-D1-NORMAL-MOTORWAY.
_RECORDING_NAME = re.compile(
    r"^(?P<started>\d{14})"
    r"-(?P<distance>[\d.]+)km"
    r"-(?P<driver>D\d+)"
    r"-(?P<behaviour>[A-Z]+)"
    r"-(?P<road_type>[A-Z]+)$"
)

# Intervals quieter than this count as near-straight driving, and are the only
# ones used to identify the longitudinal channel — cornering would otherwise
# leak lateral acceleration into the comparison.
STRAIGHT_YAW_RATE_DPS = 2.0

# Below this correlation the detection is not trustworthy enough to act on.
MIN_DETECTION_CORRELATION = 0.5


# --- Parsed rows ----------------------------------------------------------


@dataclass(frozen=True)
class AccelRow:
    t: float
    activation: bool
    x_g: float
    y_g: float
    z_g: float
    yaw_deg: float

    def channel_g(self, channel: str) -> float:
        return {"X": self.x_g, "Y": self.y_g, "Z": self.z_g}[channel]


@dataclass(frozen=True)
class GpsRow:
    t: float
    speed_kph: float
    latitude: float
    longitude: float
    course_deg: float


@dataclass(frozen=True)
class RecordingMeta:
    """Identity and labels recovered from the recording directory name."""

    recording_id: str
    driver_id: str
    behaviour: str
    road_type: str
    started_at: datetime
    distance_km: float


@dataclass(frozen=True)
class AxisMapping:
    """Which raw channel carries which acceleration, and in which direction.

    ``*_sign`` is +1 when the channel already matches DriveSense's convention
    (positive longitudinal = accelerating, matching
    ``app.core.events.thresholds``, where braking is negative) and -1 when it
    is inverted.
    """

    longitudinal: str
    longitudinal_sign: float
    lateral: str
    lateral_sign: float


@dataclass(frozen=True)
class AxisDetection:
    """The evidence behind an AxisMapping, so a caller can judge it."""

    mapping: AxisMapping
    longitudinal_correlations: dict[str, float]
    lateral_correlations: dict[str, float]
    straight_interval_count: int
    interval_count: int

    @property
    def longitudinal_strength(self) -> float:
        return abs(self.longitudinal_correlations[self.mapping.longitudinal])

    @property
    def lateral_strength(self) -> float:
        return abs(self.lateral_correlations[self.mapping.lateral])


@dataclass(frozen=True)
class UahRecording:
    meta: RecordingMeta
    samples: list[FeatureSample]
    axis_detection: AxisDetection
    skipped_accel_rows: int
    skipped_gps_rows: int


class UahParseError(ValueError):
    """The recording could not be read at all — not a per-row problem."""


# --- Angles ---------------------------------------------------------------


def wrap_degrees(delta: float) -> float:
    """Shortest signed equivalent of `delta`, in (-180, 180].

    UAH yaw is reported wrapped, so a heading crossing the +/-180 boundary
    produces a raw difference near 360 that would otherwise register as an
    enormous yaw rate.
    """
    return ((delta + 180.0) % 360.0) - 180.0


def yaw_rates_dps(rows: Sequence[AccelRow]) -> list[tuple[float, float]]:
    """(timestamp, yaw rate) pairs derived as wrapped diff(yaw)/dt.

    UAH has no native yaw-rate column, so feature 21 depends on this.
    """
    rates: list[tuple[float, float]] = []
    for prev, cur in zip(rows, rows[1:], strict=False):
        dt = cur.t - prev.t
        if dt > 0:
            rates.append((cur.t, wrap_degrees(cur.yaw_deg - prev.yaw_deg) / dt))
    return rates


# --- File parsing ---------------------------------------------------------


def _numeric_fields(line: str) -> list[str] | None:
    stripped = line.strip()
    if not stripped or stripped.startswith("#"):
        return None
    return stripped.split()


def parse_accelerometer_file(path: Path) -> tuple[list[AccelRow], int]:
    """Parse RAW_ACCELEROMETERS.txt. Returns (rows, skipped_row_count).

    A malformed row is skipped, not fatal: one truncated line in a 30-minute
    recording must not cost the whole recording.
    """
    rows: list[AccelRow] = []
    skipped = 0
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        fields = _numeric_fields(line)
        if fields is None:
            continue
        if len(fields) < ACC_MIN_COLUMNS:
            skipped += 1
            logger.debug(
                "%s:%d skipped: %d columns, need %d",
                path.name,
                lineno,
                len(fields),
                ACC_MIN_COLUMNS,
            )
            continue
        try:
            row = AccelRow(
                t=float(fields[ACC_TIMESTAMP]),
                activation=float(fields[ACC_ACTIVATION]) != 0.0,
                x_g=float(fields[ACC_X_G]),
                y_g=float(fields[ACC_Y_G]),
                z_g=float(fields[ACC_Z_G]),
                yaw_deg=float(fields[ACC_YAW]),
            )
        except ValueError as exc:
            skipped += 1
            logger.debug("%s:%d skipped: %s", path.name, lineno, exc)
            continue
        rows.append(row)

    if skipped:
        logger.warning(
            "%s: skipped %d malformed row(s) of %d", path.name, skipped, skipped + len(rows)
        )
    rows.sort(key=lambda r: r.t)
    return rows, skipped


def parse_gps_file(path: Path) -> tuple[list[GpsRow], int]:
    """Parse RAW_GPS.txt. Returns (rows, skipped_row_count)."""
    rows: list[GpsRow] = []
    skipped = 0
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        fields = _numeric_fields(line)
        if fields is None:
            continue
        if len(fields) < GPS_MIN_COLUMNS:
            skipped += 1
            logger.debug(
                "%s:%d skipped: %d columns, need %d",
                path.name,
                lineno,
                len(fields),
                GPS_MIN_COLUMNS,
            )
            continue
        try:
            row = GpsRow(
                t=float(fields[GPS_TIMESTAMP]),
                speed_kph=float(fields[GPS_SPEED_KPH]),
                latitude=float(fields[GPS_LATITUDE]),
                longitude=float(fields[GPS_LONGITUDE]),
                course_deg=float(fields[GPS_COURSE]),
            )
        except ValueError as exc:
            skipped += 1
            logger.debug("%s:%d skipped: %s", path.name, lineno, exc)
            continue
        rows.append(row)

    if skipped:
        logger.warning(
            "%s: skipped %d malformed row(s) of %d", path.name, skipped, skipped + len(rows)
        )
    rows.sort(key=lambda r: r.t)
    return rows, skipped


def parse_recording_name(name: str) -> RecordingMeta:
    """Recover driver, labels and start instant from the directory name."""
    match = _RECORDING_NAME.match(name)
    if match is None:
        raise UahParseError(
            f"{name!r} is not a UAH recording directory name "
            "(expected e.g. 20151110175712-16km-D1-NORMAL-MOTORWAY)"
        )
    return RecordingMeta(
        recording_id=name,
        driver_id=match["driver"],
        behaviour=match["behaviour"],
        road_type=match["road_type"],
        started_at=datetime.strptime(match["started"], "%Y%m%d%H%M%S"),
        distance_km=float(match["distance"]),
    )


# --- Axis detection -------------------------------------------------------


@dataclass(frozen=True)
class _Interval:
    """One GPS-to-GPS span, with accelerometer content averaged over it."""

    longitudinal_reference: float  # d(speed)/dt, m/s^2
    lateral_reference: float  # speed * yaw_rate, m/s^2
    mean_yaw_rate_dps: float
    channel_means: dict[str, float]


def _build_intervals(accel_rows: Sequence[AccelRow], gps_rows: Sequence[GpsRow]) -> list[_Interval]:
    rates = dict(yaw_rates_dps(accel_rows))
    intervals: list[_Interval] = []

    for start, end in zip(gps_rows, gps_rows[1:], strict=False):
        dt = end.t - start.t
        if dt <= 0:
            continue
        window = [r for r in accel_rows if start.t <= r.t < end.t]
        if not window:
            continue

        window_rates = [rates[r.t] for r in window if r.t in rates]
        mean_yaw_rate = statistics.fmean(window_rates) if window_rates else 0.0
        mean_speed_mps = (start.speed_kph + end.speed_kph) / 2.0 / 3.6

        intervals.append(
            _Interval(
                longitudinal_reference=(end.speed_kph - start.speed_kph) / 3.6 / dt,
                lateral_reference=mean_speed_mps * math.radians(mean_yaw_rate),
                mean_yaw_rate_dps=mean_yaw_rate,
                channel_means={
                    c: statistics.fmean([r.channel_g(c) for r in window]) for c in CHANNELS
                },
            )
        )
    return intervals


def _correlate(xs: Sequence[float], ys: Sequence[float]) -> float:
    """Pearson correlation, or 0.0 where it is undefined (constant input)."""
    if len(xs) < 2:
        return 0.0
    try:
        return statistics.correlation(xs, ys)
    except statistics.StatisticsError:
        return 0.0


def detect_axis_mapping(
    accel_rows: Sequence[AccelRow],
    gps_rows: Sequence[GpsRow],
    *,
    straight_yaw_rate_dps: float = STRAIGHT_YAW_RATE_DPS,
) -> AxisDetection:
    """Identify the longitudinal and lateral channels empirically.

    Published descriptions of the device orientation disagree, so the mapping
    is measured rather than assumed: the longitudinal channel is the one
    tracking d(speed)/dt from GPS over near-straight stretches, and the
    lateral channel is the one tracking speed * yaw_rate. The sign falls out
    of the correlation, so an inverted mounting is corrected too.
    """
    intervals = _build_intervals(accel_rows, gps_rows)
    if len(intervals) < 2:
        raise UahParseError(
            "not enough overlapping GPS/accelerometer data to determine axis mapping"
        )

    straight = [i for i in intervals if abs(i.mean_yaw_rate_dps) <= straight_yaw_rate_dps]
    if len(straight) < 2:
        raise UahParseError(
            f"no near-straight driving found (needed 2+ intervals under "
            f"{straight_yaw_rate_dps} deg/s); cannot identify the longitudinal channel"
        )

    longitudinal_correlations = {
        c: _correlate(
            [i.channel_means[c] for i in straight],
            [i.longitudinal_reference for i in straight],
        )
        for c in CHANNELS
    }
    lateral_correlations = {
        c: _correlate(
            [i.channel_means[c] for i in intervals],
            [i.lateral_reference for i in intervals],
        )
        for c in CHANNELS
    }

    longitudinal = max(CHANNELS, key=lambda c: abs(longitudinal_correlations[c]))
    lateral = max(
        (c for c in CHANNELS if c != longitudinal),
        key=lambda c: abs(lateral_correlations[c]),
    )

    for axis, channel, correlations in (
        ("longitudinal", longitudinal, longitudinal_correlations),
        ("lateral", lateral, lateral_correlations),
    ):
        strength = abs(correlations[channel])
        if strength < MIN_DETECTION_CORRELATION:
            raise UahParseError(
                f"{axis} channel is ambiguous: best candidate {channel} correlates only "
                f"{strength:.3f} (need {MIN_DETECTION_CORRELATION}); refusing to guess"
            )

    return AxisDetection(
        mapping=AxisMapping(
            longitudinal=longitudinal,
            longitudinal_sign=math.copysign(1.0, longitudinal_correlations[longitudinal]),
            lateral=lateral,
            lateral_sign=math.copysign(1.0, lateral_correlations[lateral]),
        ),
        longitudinal_correlations=longitudinal_correlations,
        lateral_correlations=lateral_correlations,
        straight_interval_count=len(straight),
        interval_count=len(intervals),
    )


# --- Assembly -------------------------------------------------------------


def _forward_filled_gps(
    accel_rows: Sequence[AccelRow], gps_rows: Sequence[GpsRow]
) -> list[tuple[AccelRow, GpsRow]]:
    """Pair each accelerometer row with the most recent GPS fix at or before it.

    Accelerometer rows preceding the first fix are dropped: no speed exists
    for them and back-filling would fabricate one.
    """
    paired: list[tuple[AccelRow, GpsRow]] = []
    index = -1
    for row in accel_rows:
        while index + 1 < len(gps_rows) and gps_rows[index + 1].t <= row.t:
            index += 1
        if index >= 0:
            paired.append((row, gps_rows[index]))
    return paired


def build_samples(
    accel_rows: Sequence[AccelRow],
    gps_rows: Sequence[GpsRow],
    mapping: AxisMapping,
) -> list[FeatureSample]:
    """Merge the two streams onto the 10 Hz accelerometer grid."""
    rates = dict(yaw_rates_dps(accel_rows))
    samples: list[FeatureSample] = []

    for row, fix in _forward_filled_gps(accel_rows, gps_rows):
        samples.append(
            FeatureSample(
                # Placeholder start; load_recording rebases onto the real instant.
                recorded_at=datetime.min + timedelta(seconds=row.t),
                speed_kph=fix.speed_kph,
                accel_ms2=mapping.longitudinal_sign
                * row.channel_g(mapping.longitudinal)
                * G_TO_MS2,
                lateral_accel_ms2=mapping.lateral_sign * row.channel_g(mapping.lateral) * G_TO_MS2,
                yaw_rate_dps=rates.get(row.t),
                heading_deg=fix.course_deg % 360.0,
                lat=fix.latitude,
                lon=fix.longitude,
            )
        )
    return samples


def load_recording(directory: Path, *, axis_mapping: AxisMapping | None = None) -> UahRecording:
    """Load one UAH recording directory into FeatureSamples.

    `axis_mapping` overrides detection — pass the mapping established across
    the whole dataset once it is known, so a single quiet recording cannot
    silently adopt a different convention from its neighbours.
    """
    accel_path = directory / ACCEL_FILENAME
    gps_path = directory / GPS_FILENAME
    for path in (accel_path, gps_path):
        if not path.is_file():
            raise UahParseError(f"{path} not found")

    meta = parse_recording_name(directory.name)
    accel_rows, skipped_accel = parse_accelerometer_file(accel_path)
    gps_rows, skipped_gps = parse_gps_file(gps_path)

    if not accel_rows or not gps_rows:
        raise UahParseError(f"{directory.name}: no usable rows after parsing")

    detection = detect_axis_mapping(accel_rows, gps_rows)
    mapping = axis_mapping or detection.mapping

    samples = [
        FeatureSample(
            recorded_at=meta.started_at + (s.recorded_at - datetime.min),
            speed_kph=s.speed_kph,
            accel_ms2=s.accel_ms2,
            lateral_accel_ms2=s.lateral_accel_ms2,
            yaw_rate_dps=s.yaw_rate_dps,
            heading_deg=s.heading_deg,
            lat=s.lat,
            lon=s.lon,
        )
        for s in build_samples(accel_rows, gps_rows, mapping)
    ]

    return UahRecording(
        meta=meta,
        samples=samples,
        axis_detection=detection,
        skipped_accel_rows=skipped_accel,
        skipped_gps_rows=skipped_gps,
    )


def find_recordings(root: Path) -> list[Path]:
    """Every directory under `root` whose name parses as a UAH recording."""
    if not root.is_dir():
        return []
    return sorted(d for d in root.rglob("*") if d.is_dir() and _RECORDING_NAME.match(d.name))


def load_recordings(
    directories: Iterable[Path], *, axis_mapping: AxisMapping | None = None
) -> list[UahRecording]:
    """Load several recordings, skipping any that fail rather than aborting."""
    recordings: list[UahRecording] = []
    for directory in directories:
        try:
            recordings.append(load_recording(directory, axis_mapping=axis_mapping))
        except UahParseError:
            logger.exception("skipping unreadable recording %s", directory)
    return recordings
