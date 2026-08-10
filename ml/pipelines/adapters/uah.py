"""UAH-DriveSet -> FeatureSample adapter.

Parses a single UAH-DriveSet recording directory (``RAW_ACCELEROMETERS.txt``
and ``RAW_GPS.txt``) into the shared ``FeatureSample`` sequence that
``app.core.features`` consumes. Everything dataset-specific — units, axis
convention, resampling, file layout — is confined here; the shared feature
module never learns what UAH is (ADR 0004).

Column layout confirmed against the dataset author's own reader tool, which
ships inside the bundle at ``uah_driveset_reader/driveset_reader.py``.

Decisions recorded here because they change the numbers downstream:

*Raw, not Kalman-filtered, channels for features.* The KF columns (5-7) are
smoother, but the smoothing suppresses exactly the high-frequency content
that features 14, 15 and 20 (``jerk_std``, ``jerk_max_abs``,
``accel_magnitude_max``) exist to measure. Axis *detection* uses the KF
columns, where smoothing helps rather than hurts; the features themselves
still come from raw.

*Forward-fill, never interpolate.* GPS is 1 Hz and accelerometers are 10 Hz.
Each accelerometer sample takes the speed/course of the most recent GPS fix
at or before it. Samples preceding the first fix are dropped rather than
back-filled — a speed we do not have must not be invented.

*GPS fixes are quality-filtered.* Real recordings open with an invalid fix
(``speed=0.0, course=-1, horizontal_accuracy=201``). Left in, the 0 -> 79 km/h
jump fabricates a +21 m/s^2 acceleration and destroys axis detection. Fixes
worse than ``MAX_HORIZONTAL_ACCURACY_M`` or carrying a negative course are
dropped before any reference signal is computed.

*The accelerometer yaw column is not used as a heading.* Despite the reader
tool labelling it "Yaw (degrees)", measurements across all 40 recordings show
it is radian-scale (it spans 4.2 units where GPS course spans 258 degrees)
and it does not agree with GPS course in absolute terms. Its *derivative*
does track real turning — corr(yaw rate, GPS course rate) has median -0.63
with slope -0.86, i.e. correct magnitude but inverted sign — so it survives
here only as an unscaled turn-rate proxy for identifying the lateral channel,
never as a heading and never as a feature input. Feature 21
(``yaw_rate_std``) is derived from GPS course instead; see
``course_rates_dps``.
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
ACC_ACTIVATION = 1  # 1 if speed > 50 km/h — a speed flag, NOT a calibration flag
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
# The behaviour label may carry a numeric suffix: the secondary-road normal
# drives are split into NORMAL1 and NORMAL2 for drivers D1-D5. Without the
# `\d*` those ten recordings — a quarter of the dataset — are silently missed.
_RECORDING_NAME = re.compile(
    r"^(?P<started>\d{14})"
    r"-(?P<distance>[\d.]+)km"
    r"-(?P<driver>D\d+)"
    r"-(?P<behaviour>[A-Z]+\d*)"
    r"-(?P<road_type>[A-Z]+)$"
)

# Fixes worse than this (metres) are dropped; see the module docstring.
MAX_HORIZONTAL_ACCURACY_M = 20.0

# GPS speed lags the accelerometers. The lag is not fixed across recordings
# (measured range -2.75 s .. +3.00 s, median -1.1 s), so it is swept per
# recording rather than assumed.
LAG_SWEEP_SECONDS = tuple(i * 0.25 for i in range(-12, 13))

# A GPS interval longer than this spans a gap left by dropped fixes, and its
# endpoints are too far apart to describe a single acceleration.
MAX_INTERVAL_SECONDS = 3.0

# Intervals quieter than this count as near-straight driving, and are the only
# ones used to identify the longitudinal channel — cornering would otherwise
# leak lateral acceleration into the comparison.
STRAIGHT_LATERAL_REFERENCE_MS2 = 0.5

# Acceptance threshold for a detected correlation. Set from the measured
# distribution rather than taste: across 40 real recordings the longitudinal
# correlation runs 0.196 .. 0.734 (median 0.439) and the lateral 0.043 ..
# 0.796 (median 0.379). A typical recording contributes ~800 intervals, where
# the p=0.001 significance floor is |r| ~ 3.3/sqrt(800) ~ 0.117; 0.15 sits
# just above that and admits every real recording. An earlier 0.5 — picked by
# taste, not measurement — rejected all 40.
MIN_DETECTION_CORRELATION = 0.15

MIN_DETECTION_INTERVALS = 10


# --- Parsed rows ----------------------------------------------------------


@dataclass(frozen=True)
class AccelRow:
    t: float
    activation: bool
    x_g: float
    y_g: float
    z_g: float
    yaw: float  # radian-scale, phone frame; only its derivative is meaningful
    x_kf_g: float = 0.0
    y_kf_g: float = 0.0
    z_kf_g: float = 0.0

    def channel_g(self, channel: str) -> float:
        return {"X": self.x_g, "Y": self.y_g, "Z": self.z_g}[channel]

    def channel_kf_g(self, channel: str) -> float:
        return {"X": self.x_kf_g, "Y": self.y_kf_g, "Z": self.z_kf_g}[channel]


@dataclass(frozen=True)
class GpsRow:
    t: float
    speed_kph: float
    latitude: float
    longitude: float
    course_deg: float
    horizontal_accuracy_m: float = 0.0
    vertical_accuracy_m: float = 0.0
    difcourse: float = 0.0

    @property
    def is_usable(self) -> bool:
        """A fix good enough to derive speed and heading references from."""
        return (
            0.0 <= self.horizontal_accuracy_m <= MAX_HORIZONTAL_ACCURACY_M
            and self.course_deg >= 0.0
        )


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
    lag_seconds: float
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
    discarded_gps_fixes: int


class UahParseError(ValueError):
    """The recording could not be read at all — not a per-row problem."""


# --- Angles ---------------------------------------------------------------


def wrap_degrees(delta: float) -> float:
    """Shortest signed equivalent of `delta` degrees, in (-180, 180]."""
    return ((delta + 180.0) % 360.0) - 180.0


def wrap_radians(delta: float) -> float:
    """Shortest signed equivalent of `delta` radians, in (-pi, pi]."""
    return ((delta + math.pi) % (2.0 * math.pi)) - math.pi


def course_rates_dps(gps_rows: Sequence[GpsRow]) -> list[tuple[float, float]]:
    """(timestamp, heading rate in deg/s) derived from GPS course.

    This is the source for feature 21 (`yaw_rate_std`). GPS course is a true
    heading in degrees; the accelerometer yaw column is not (see module
    docstring).

    `difcourse` (column 8) is deliberately not used: it correlates only -0.39
    with the course delta recomputed from consecutive fixes, so whatever it
    measures, it is not this. Rederiving from `course` keeps the quantity
    defined by something we can check.
    """
    rates: list[tuple[float, float]] = []
    for prev, cur in zip(gps_rows, gps_rows[1:], strict=False):
        dt = cur.t - prev.t
        if 0.0 < dt <= MAX_INTERVAL_SECONDS:
            rates.append((cur.t, wrap_degrees(cur.course_deg - prev.course_deg) / dt))
    return rates


def yaw_turn_rate_proxy(rows: Sequence[AccelRow]) -> dict[float, float]:
    """Unscaled turn-rate proxy from the accelerometer yaw column.

    Used *only* to identify which channel is lateral, where its 10 Hz cadence
    beats 1 Hz GPS course by a wide margin (median |r| 0.38 vs 0.11, and it
    picks the same channel on 38 of 40 recordings where GPS course picks the
    wrong one on 26). Correlation is scale- and sign-invariant, so the
    column's unknown scale and inverted sign do not matter here. It is never
    used as a heading and never reaches a feature.
    """
    proxy: dict[float, float] = {}
    for prev, cur in zip(rows, rows[1:], strict=False):
        dt = cur.t - prev.t
        if dt > 0:
            proxy[cur.t] = math.degrees(wrap_radians(cur.yaw - prev.yaw)) / dt
    return proxy


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
                yaw=float(fields[ACC_YAW]),
                x_kf_g=float(fields[ACC_X_KF]),
                y_kf_g=float(fields[ACC_Y_KF]),
                z_kf_g=float(fields[ACC_Z_KF]),
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
    """Parse RAW_GPS.txt. Returns (rows, skipped_row_count).

    Rows are parsed regardless of fix quality; filtering happens in
    `usable_fixes` so callers can see what was discarded and why.
    """
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
                horizontal_accuracy_m=float(fields[GPS_HORIZONTAL_ACCURACY]),
                vertical_accuracy_m=float(fields[GPS_VERTICAL_ACCURACY]),
                difcourse=float(fields[GPS_DIFCOURSE]),
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


def usable_fixes(gps_rows: Sequence[GpsRow]) -> list[GpsRow]:
    """Drop fixes too inaccurate to derive reference signals from."""
    return [row for row in gps_rows if row.is_usable]


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
    lateral_reference: float  # speed * turn rate, m/s^2 (unscaled)
    channel_means: dict[str, float]


def _build_intervals(
    accel_rows: Sequence[AccelRow], gps_rows: Sequence[GpsRow], lag_seconds: float
) -> list[_Interval]:
    """Pair GPS intervals with the accelerometer window shifted by `lag_seconds`."""
    proxy = yaw_turn_rate_proxy(accel_rows)
    intervals: list[_Interval] = []
    cursor = 0

    for start, end in zip(gps_rows, gps_rows[1:], strict=False):
        dt = end.t - start.t
        if not 0.0 < dt <= MAX_INTERVAL_SECONDS:
            continue

        low, high = start.t + lag_seconds, end.t + lag_seconds
        while cursor > 0 and accel_rows[cursor - 1].t >= low:
            cursor -= 1
        while cursor < len(accel_rows) and accel_rows[cursor].t < low:
            cursor += 1
        window = []
        scan = cursor
        while scan < len(accel_rows) and accel_rows[scan].t < high:
            window.append(accel_rows[scan])
            scan += 1
        if not window:
            continue

        turn_rates = [proxy[r.t] for r in window if r.t in proxy]
        mean_turn_rate = statistics.fmean(turn_rates) if turn_rates else 0.0
        mean_speed_mps = (start.speed_kph + end.speed_kph) / 2.0 / 3.6

        intervals.append(
            _Interval(
                longitudinal_reference=(end.speed_kph - start.speed_kph) / 3.6 / dt,
                lateral_reference=mean_speed_mps * math.radians(mean_turn_rate),
                channel_means={
                    c: statistics.fmean([r.channel_kf_g(c) for r in window]) for c in CHANNELS
                },
            )
        )
    return intervals


def _correlate(xs: Sequence[float], ys: Sequence[float]) -> float:
    """Pearson correlation, or 0.0 where it is undefined (constant input)."""
    if len(xs) < 2:
        return 0.0
    try:
        value = statistics.correlation(xs, ys)
    except statistics.StatisticsError:
        return 0.0
    return 0.0 if math.isnan(value) else value


def detect_axis_mapping(
    accel_rows: Sequence[AccelRow],
    gps_rows: Sequence[GpsRow],
    *,
    lags: Sequence[float] = LAG_SWEEP_SECONDS,
) -> AxisDetection:
    """Identify the longitudinal and lateral channels empirically.

    Published descriptions of the device orientation disagree, so the mapping
    is measured rather than assumed. The longitudinal channel is the one
    tracking d(speed)/dt from GPS over near-straight stretches; the lateral
    channel is whichever of the remaining two tracks speed * turn rate. The
    sign falls out of the correlation, so an inverted mounting is corrected.

    GPS speed lags the accelerometers by a recording-dependent amount, so
    `lags` is swept and the alignment with the strongest longitudinal
    correlation wins. Detection reads the KF-smoothed channels, which lifts
    the longitudinal correlation slightly (median 0.439 vs 0.432) at no cost —
    features are still computed from the raw columns.
    """
    fixes = usable_fixes(gps_rows)
    if len(fixes) < MIN_DETECTION_INTERVALS or not accel_rows:
        raise UahParseError("not enough usable GPS fixes to determine axis mapping")

    best: tuple[float, list[_Interval], dict[str, float], str] | None = None
    for lag in lags:
        intervals = _build_intervals(accel_rows, fixes, lag)
        if len(intervals) < MIN_DETECTION_INTERVALS:
            continue
        straight = [
            i for i in intervals if abs(i.lateral_reference) < STRAIGHT_LATERAL_REFERENCE_MS2
        ]
        pool = straight if len(straight) >= MIN_DETECTION_INTERVALS else intervals
        correlations = {
            c: _correlate(
                [i.channel_means[c] for i in pool],
                [i.longitudinal_reference for i in pool],
            )
            for c in CHANNELS
        }
        winner = max(CHANNELS, key=lambda c: abs(correlations[c]))
        if best is None or abs(correlations[winner]) > abs(best[2][best[3]]):
            best = (lag, intervals, correlations, winner)

    if best is None:
        raise UahParseError(
            "not enough overlapping GPS/accelerometer data to determine axis mapping"
        )

    lag, intervals, longitudinal_correlations, longitudinal = best
    straight = [i for i in intervals if abs(i.lateral_reference) < STRAIGHT_LATERAL_REFERENCE_MS2]

    lateral_correlations = {
        c: _correlate(
            [i.channel_means[c] for i in intervals],
            [i.lateral_reference for i in intervals],
        )
        for c in CHANNELS
    }
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
        lag_seconds=lag,
        straight_interval_count=len(straight),
        interval_count=len(intervals),
    )


@dataclass(frozen=True)
class DatasetAxisConsensus:
    """The mapping agreed across many recordings, plus the vote that produced it."""

    mapping: AxisMapping
    longitudinal_votes: dict[str, int]
    lateral_votes: dict[str, int]
    agreeing: int
    undetectable: int

    @property
    def total(self) -> int:
        return self.agreeing + self.undetectable


def dataset_axis_mapping(directories: Iterable[Path]) -> DatasetAxisConsensus:
    """Settle the axis mapping across a whole dataset by majority vote.

    The mounting is a property of the capture rig, not of any one drive, and
    per-recording detection is not uniformly reliable: motorway drives contain
    so little cornering that the lateral reference carries no usable signal,
    and 5 of the 40 UAH recordings cannot resolve lateral on their own. Voting
    over the recordings that *can* resolve it, then passing the result to
    `load_recording(..., axis_mapping=...)`, is both more robust than trusting
    each recording and stricter — a recording that disagreed would show up as
    a split vote rather than silently adopting its own convention.
    """
    longitudinal_votes: dict[str, int] = {}
    lateral_votes: dict[str, int] = {}
    longitudinal_signs: list[float] = []
    lateral_signs: list[float] = []
    undetectable = 0

    for directory in directories:
        try:
            accel_rows, _ = parse_accelerometer_file(directory / ACCEL_FILENAME)
            gps_rows, _ = parse_gps_file(directory / GPS_FILENAME)
            detection = detect_axis_mapping(accel_rows, gps_rows)
        except (UahParseError, OSError):
            undetectable += 1
            continue
        mapping = detection.mapping
        longitudinal_votes[mapping.longitudinal] = (
            longitudinal_votes.get(mapping.longitudinal, 0) + 1
        )
        lateral_votes[mapping.lateral] = lateral_votes.get(mapping.lateral, 0) + 1
        longitudinal_signs.append(mapping.longitudinal_sign)
        lateral_signs.append(mapping.lateral_sign)

    if not longitudinal_votes:
        raise UahParseError("no recording produced a confident axis detection")

    longitudinal = max(longitudinal_votes, key=lambda c: longitudinal_votes[c])
    lateral = max(lateral_votes, key=lambda c: lateral_votes[c])
    return DatasetAxisConsensus(
        mapping=AxisMapping(
            longitudinal=longitudinal,
            longitudinal_sign=math.copysign(1.0, statistics.fmean(longitudinal_signs)),
            lateral=lateral,
            lateral_sign=math.copysign(1.0, statistics.fmean(lateral_signs)),
        ),
        longitudinal_votes=longitudinal_votes,
        lateral_votes=lateral_votes,
        agreeing=sum(longitudinal_votes.values()),
        undetectable=undetectable,
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


def _forward_filled_rate(timestamp: float, rates: Sequence[tuple[float, float]]) -> float | None:
    """Most recent heading rate at or before `timestamp`, or None before the first."""
    latest: float | None = None
    for t, rate in rates:
        if t > timestamp:
            break
        latest = rate
    return latest


def build_samples(
    accel_rows: Sequence[AccelRow],
    gps_rows: Sequence[GpsRow],
    mapping: AxisMapping,
) -> list[FeatureSample]:
    """Merge the two streams onto the 10 Hz accelerometer grid."""
    fixes = usable_fixes(gps_rows)
    rates = course_rates_dps(fixes)
    samples: list[FeatureSample] = []
    rate_index = 0
    latest_rate: float | None = None

    for row, fix in _forward_filled_gps(accel_rows, fixes):
        while rate_index < len(rates) and rates[rate_index][0] <= row.t:
            latest_rate = rates[rate_index][1]
            rate_index += 1
        samples.append(
            FeatureSample(
                # Placeholder start; load_recording rebases onto the real instant.
                recorded_at=datetime.min + timedelta(seconds=row.t),
                speed_kph=fix.speed_kph,
                accel_ms2=mapping.longitudinal_sign
                * row.channel_g(mapping.longitudinal)
                * G_TO_MS2,
                lateral_accel_ms2=mapping.lateral_sign * row.channel_g(mapping.lateral) * G_TO_MS2,
                yaw_rate_dps=latest_rate,
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

    fixes = usable_fixes(gps_rows)
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
        discarded_gps_fixes=len(gps_rows) - len(fixes),
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
