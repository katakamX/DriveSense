"""Turns raw OBD rows into the 7 risk-engine features that are honestly
derivable from `Speed_kmh` alone, then into a `RiskAssessment`.

## Why resample to 10 Hz before differentiating

The source file samples at ~0.03s (≈33 Hz). Differentiating consecutive raw
frames is dominated by logging/quantisation noise, not real vehicle
dynamics: on this repo's own sample fixture, naive frame-to-frame
differentiation produces accelerations up to ±30 m/s^2 — several times a
real car's physical limit, and far past even `HARSH_BRAKING_ACCEL_MS2`
(-3.5) or `RAPID_ACCELERATION_ACCEL_MS2` (3.0) in `app.core.events.thresholds`,
which would make every window "harsh brake" on noise alone.

10 Hz is not an arbitrary smoothing choice: `app.core.events.thresholds`
states its own debounce constants (`MIN_EVENT_FRAMES = 3`,
`MIN_RELEASE_FRAMES = 5`) are frame counts "at the 10 Hz telemetry rate this
system samples at". Feeding those detectors samples at any other cadence
means their 0.3s/0.5s debounce windows are silently wrong. Resampling to
10 Hz is therefore a correctness requirement for reusing
`app.core.events.detectors` unmodified, not just a noise-reduction nicety.

The resample takes the *mean* speed within each 0.1s bucket (not
nearest-sample or first-sample), which averages out jitter within the
bucket rather than picking one arbitrary noisy reading from it. A light
3-tap moving average on the resampled series further reduces the residual
noise before differentiating. Verified against `sample_obd.csv`: naive
differentiation has a population std of ~4.0 m/s^2 and a ±30 m/s^2 range;
resample + smoothing brings that to a std of ~1.6 m/s^2 and a roughly
±5-6 m/s^2 range — a plausible envelope for real (if aggressive) driving,
and one where the existing thresholds (calibrated in the same units) can
mean something again. See `tests/test_obd_features.py`.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

from app.core.features import extract
from app.core.features.extract import FeatureContext
from app.core.features.schema import FeatureSample
from app.core.obd.parse import ObdRow
from app.core.risk import rules
from app.core.risk.schema import (
    BAND_SEVERITY,
    RISK_ENGINE_VERSION,
    Provenance,
    RiskAssessment,
)
from app.core.risk.score import RULE_ONLY_CONFIDENCE

# Matches the live pipeline's assumed cadence (`Settings.telemetry_rate_hz`)
# and the frame-count debounce constants in `app.core.events.thresholds` —
# see this module's docstring for why that is a correctness requirement, not
# a style choice.
RESAMPLE_RATE_HZ = 10.0
RESAMPLE_INTERVAL_S = 1.0 / RESAMPLE_RATE_HZ

# Distinct from `app.core.features.schema.FEATURE_VERSION`: an OBD-derived
# assessment is not the 26-feature GPS/IMU vector that name identifies, only
# 7 of them. Keeping a separate tag means a stored assessment's provenance
# says which basis produced it rather than implying full compatibility.
OBD_FEATURE_VERSION = "obd-1"

# `lateral_accel_ms2` is a required (non-Optional) field on `FeatureSample`,
# but `evaluate_obd` never reads it — see `app.core.risk.rules.evaluate_obd`.
# This constant exists only to satisfy that structural requirement; it is
# never treated as measured lateral data anywhere downstream.
_UNUSED_LATERAL_PLACEHOLDER = 0.0


def _resample_and_smooth(rows: Sequence[ObdRow]) -> list[tuple[float, float]]:
    """Bucket-mean resample to `RESAMPLE_INTERVAL_S`, then a 3-tap moving average.

    Returns `(time_s, speed_kmh)` pairs, ordered by time. Buckets with no
    source rows (a gap in the upload) are simply absent rather than
    interpolated — a caller building `FeatureSample`s from a shorter list
    gets a lower `sample_count`/`coverage_ratio`, which is the same honesty
    property the live pipeline's window coverage already has.
    """
    buckets: dict[int, list[float]] = {}
    for row in sorted(rows, key=lambda r: r.time_s):
        bucket_index = round(row.time_s / RESAMPLE_INTERVAL_S)
        buckets.setdefault(bucket_index, []).append(row.speed_kmh)

    ordered_buckets = sorted(buckets.items())
    resampled = [
        (index * RESAMPLE_INTERVAL_S, sum(speeds) / len(speeds))
        for index, speeds in ordered_buckets
    ]

    speeds = [speed for _, speed in resampled]
    smoothed = []
    for i in range(len(speeds)):
        lo, hi = max(0, i - 1), min(len(speeds), i + 2)
        smoothed.append(sum(speeds[lo:hi]) / (hi - lo))

    return [(t, s) for (t, _), s in zip(resampled, smoothed, strict=True)]


def obd_rows_to_feature_samples(
    rows: Sequence[ObdRow], *, base_time: datetime
) -> list[FeatureSample]:
    """Resample + differentiate `rows` into the `FeatureSample`s the shared
    feature functions expect. `base_time` anchors `Time_s == 0`.

    Requires at least 2 resampled points to produce one differentiated
    sample; returns `[]` for anything shorter (mirrors
    `extract_features`'s "at least one sample" contract by leaving the
    "raise on empty" decision to the caller, since a replay chunk being
    momentarily too short is not exceptional the way an empty upload is).
    """
    resampled = _resample_and_smooth(rows)
    if len(resampled) < 2:
        return []

    samples: list[FeatureSample] = []
    for (t0, s0), (t1, s1) in zip(resampled, resampled[1:], strict=False):
        dt = t1 - t0
        if dt <= 0:
            continue
        accel_ms2 = ((s1 - s0) / 3.6) / dt
        samples.append(
            FeatureSample(
                recorded_at=base_time + timedelta(seconds=t1),
                speed_kph=s1,
                accel_ms2=accel_ms2,
                lateral_accel_ms2=_UNUSED_LATERAL_PLACEHOLDER,
            )
        )
    return samples


def assess_obd_window(
    samples: Sequence[FeatureSample],
    *,
    window_start: datetime,
    window_end: datetime,
    speed_limit_kph: float,
    expected_sample_count: int | None = None,
) -> RiskAssessment:
    """One window's worth of OBD-derived samples, scored the same way a live
    rules-only window is (see `score.assess`'s `model_output=None` branch,
    which this mirrors) — there is no model here to consult; OBD analysis is
    `RULES_ONLY` by construction, not by omission. See STEP4_FINDINGS.md.
    """
    if not samples:
        raise ValueError("assess_obd_window requires at least one sample")

    ordered = sorted(samples, key=lambda s: s.recorded_at)
    values = {
        "speed_cv": extract.speed_cv(ordered),
        "accel_min": extract.accel_min(ordered),
        "accel_max": extract.accel_max(ordered),
        "accel_std": extract.accel_std(ordered),
        "harsh_braking_per_min": extract.harsh_braking_per_min(ordered),
        "rapid_accel_per_min": extract.rapid_accel_per_min(ordered),
        "speeding_time_ratio": extract.speeding_time_ratio(
            ordered, FeatureContext(speed_limit_kph=speed_limit_kph)
        ),
    }
    outcome = rules.evaluate_obd(values)

    denom = expected_sample_count if expected_sample_count is not None else len(ordered)
    coverage_ratio = min(len(ordered) / denom, 1.0) if denom > 0 else 0.0
    coverage_factor = min(max(coverage_ratio, 0.0), 1.0)

    return RiskAssessment(
        risk_engine_version=RISK_ENGINE_VERSION,
        feature_version=OBD_FEATURE_VERSION,
        rubric_version=rules.RUBRIC_VERSION,
        model_version=None,
        window_start=window_start,
        window_end=window_end,
        sample_count=len(ordered),
        coverage_ratio=coverage_ratio,
        score=BAND_SEVERITY[outcome.band],
        band=outcome.band,
        confidence=RULE_ONLY_CONFIDENCE * coverage_factor,
        provenance=Provenance.RULES_ONLY,
        model_available=False,
        gated=False,
        rule_band=outcome.band,
        matched_rules=outcome.matched,
        model_band=None,
        model_score=None,
        model_predicted_class=None,
        probabilities=None,
    )


# --- Replay: the whole file as a sequence of chunked assessments ----------

# How often the replay advances, in seconds of the *recording's* own
# timeline — not wall-clock playback speed, which is the frontend's concern.
DEFAULT_CHUNK_INTERVAL_S = 1.0

# Trailing window each chunk's risk assessment covers, matching the live
# pipeline's 30s window (DESIGN_PLAN.md's "trace" element and `RiskWindow`
# both assume this size). Early chunks see a window still filling up —
# that is real, honest partial coverage, the same as a live drive's first
# 30 seconds, not a bug to hide.
DEFAULT_WINDOW_S = 30.0


@dataclass(frozen=True, slots=True)
class ReplayChunk:
    """One playback step: the raw OBD reading at `t`, plus the trailing-window
    risk assessment as of that point — or `None` if too little of the
    recording has played to compute one yet."""

    t: float
    speed_kmh: float
    rpm: float
    gear: int
    throttle_pct: float
    brake_pct: float
    assessment: RiskAssessment | None


def build_replay(
    rows: Sequence[ObdRow],
    *,
    base_time: datetime,
    speed_limit_kph: float,
    chunk_interval_s: float = DEFAULT_CHUNK_INTERVAL_S,
    window_s: float = DEFAULT_WINDOW_S,
) -> list[ReplayChunk]:
    """The whole upload, replayed as `ReplayChunk`s at `chunk_interval_s`
    steps through the recording's own `Time_s` timeline.

    Mirrors the live pipeline's shape on purpose: telemetry (here, the raw
    OBD reading) advances every chunk, while risk is a trailing `window_s`
    assessment recomputed at each step — the OBD equivalent of "telemetry at
    10 Hz, risk at 1 Hz" from the live drive. `chunk_interval_s` is
    independent of `RESAMPLE_RATE_HZ`: the latter governs how the
    accelerometer-equivalent signal is derived (see this module's docstring),
    the former is how often a new reading is surfaced to a viewer.
    """
    if not rows:
        raise ValueError("build_replay requires at least one row")

    ordered_rows = sorted(rows, key=lambda r: r.time_s)
    duration_s = ordered_rows[-1].time_s

    feature_samples = obd_rows_to_feature_samples(ordered_rows, base_time=base_time)
    sample_offsets = [(s.recorded_at - base_time).total_seconds() for s in feature_samples]

    chunk_times: list[float] = []
    t = chunk_interval_s
    while t < duration_s:
        chunk_times.append(round(t, 6))
        t += chunk_interval_s
    if not chunk_times or chunk_times[-1] < duration_s:
        chunk_times.append(round(duration_s, 6))

    chunks: list[ReplayChunk] = []
    row_index = 0
    window_lo = window_hi = 0
    n_samples = len(feature_samples)

    # Fixed, not scaled by elapsed time — matches the live ticker
    # (`app.core.windowing.ticker._run`'s `expected_samples`), whose window
    # is always "a full 30s", not "however much of the trip has happened so
    # far". A window that hasn't existed for 30s yet is genuinely
    # under-covered, the same as a live drive's first 30 seconds — that's
    # what makes coverage_ratio climb toward 1.0 rather than start there.
    expected_count = max(1, round(window_s * RESAMPLE_RATE_HZ))

    for chunk_t in chunk_times:
        # Advance the "current reading" pointer to the last row at or before
        # this chunk's time — the raw telemetry a viewer would see right now,
        # distinct from the resampled/smoothed series feeding the risk math.
        while row_index + 1 < len(ordered_rows) and ordered_rows[row_index + 1].time_s <= chunk_t:
            row_index += 1
        row = ordered_rows[row_index]

        # Two-pointer trailing window over the (monotonic) sample timeline —
        # O(samples + chunks) total rather than rescanning per chunk.
        window_start_t = max(0.0, chunk_t - window_s)
        while window_hi < n_samples and sample_offsets[window_hi] <= chunk_t:
            window_hi += 1
        while window_lo < window_hi and sample_offsets[window_lo] <= window_start_t:
            window_lo += 1
        window_samples = feature_samples[window_lo:window_hi]

        assessment = None
        if len(window_samples) >= 2:
            assessment = assess_obd_window(
                window_samples,
                window_start=base_time + timedelta(seconds=window_start_t),
                window_end=base_time + timedelta(seconds=chunk_t),
                speed_limit_kph=speed_limit_kph,
                expected_sample_count=expected_count,
            )

        chunks.append(
            ReplayChunk(
                t=chunk_t,
                speed_kmh=row.speed_kmh,
                rpm=row.rpm,
                gear=row.gear,
                throttle_pct=row.throttle_pct,
                brake_pct=row.brake_pct,
                assessment=assessment,
            )
        )

    return chunks
