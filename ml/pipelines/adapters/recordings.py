"""Simulator JSONL -> FeatureSample adapter.

The simulator (see `simulator/`) writes one recording as a pair of files:
``<trip_id>.jsonl`` (one `TelemetryFrame`-shaped JSON object per line, at
`TripMeta.sample_rate_hz`) and ``<trip_id>.meta.json`` (the `TripMeta`
sidecar). Unlike UAH-DriveSet, the simulator already emits every field the
shared `FeatureSample` schema knows about — including the extended ones
(throttle, brake, gear, RPM, engine load, clutch) — so this adapter is a
straight field mapping rather than a reconstruction.

Frames are read as plain JSON rather than validated against the
`drivesense_contracts.TelemetryFrame` pydantic model: that package is not a
dependency of `ml/`, and the pipeline only needs a handful of fields, not
full schema enforcement. A malformed line is skipped, not fatal, matching
the UAH adapter's tolerance for a few bad rows in an otherwise good
recording.

There is no driver concept for simulator recordings yet — the simulator
does not tag runs with a driver profile — so `RecordingMeta.driver_id` is
always `None` here until that exists.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from app.core.features import FeatureSample

logger = logging.getLogger(__name__)

META_SUFFIX = ".meta.json"


@dataclass(frozen=True)
class RecordingMeta:
    """Identity recovered from a simulator recording's meta sidecar."""

    recording_id: str
    driver_id: str | None
    started_at: datetime
    sample_rate_hz: float
    distance_km: float | None


@dataclass(frozen=True)
class SimRecording:
    meta: RecordingMeta
    samples: list[FeatureSample]
    skipped_rows: int


class SimParseError(ValueError):
    """The recording could not be read at all — not a per-row problem."""


def _parse_frame(payload: dict[str, object]) -> tuple[FeatureSample, float]:
    """One JSONL line -> (sample, distance_m so far)."""

    def _optional_float(key: str) -> float | None:
        value = payload.get(key)
        return None if value is None else float(value)  # type: ignore[arg-type]

    def _optional_int(key: str) -> int | None:
        value = payload.get(key)
        return None if value is None else int(float(value))  # type: ignore[arg-type]

    sample = FeatureSample(
        recorded_at=datetime.fromisoformat(str(payload["ts"])),
        speed_kph=float(payload["speed_kph"]),  # type: ignore[arg-type]
        accel_ms2=float(payload["accel_ms2"]),  # type: ignore[arg-type]
        lateral_accel_ms2=float(payload["lateral_accel_ms2"]),  # type: ignore[arg-type]
        yaw_rate_dps=_optional_float("yaw_rate_dps"),
        heading_deg=_optional_float("heading_deg"),
        lat=_optional_float("lat"),
        lon=_optional_float("lon"),
        throttle_pct=_optional_float("throttle_pct"),
        brake_pct=_optional_float("brake_pct"),
        gear=_optional_int("gear"),
        engine_rpm=_optional_float("engine_rpm"),
        engine_load_pct=_optional_float("engine_load_pct"),
        clutch_pct=_optional_float("clutch_pct"),
    )
    distance_m = float(payload.get("distance_m") or 0.0)  # type: ignore[arg-type]
    return sample, distance_m


def find_recordings(root: Path) -> list[Path]:
    """Every ``*.jsonl`` file directly under `root` that has a meta sidecar."""
    if not root.is_dir():
        return []
    return sorted(
        p for p in root.glob("*.jsonl") if (p.parent / f"{p.stem}{META_SUFFIX}").is_file()
    )


def load_recording(jsonl_path: Path) -> SimRecording:
    """Load one simulator recording (JSONL + meta sidecar) into FeatureSamples."""
    meta_path = jsonl_path.parent / f"{jsonl_path.stem}{META_SUFFIX}"
    if not jsonl_path.is_file():
        raise SimParseError(f"{jsonl_path} not found")
    if not meta_path.is_file():
        raise SimParseError(f"{meta_path} not found")

    try:
        meta_payload = json.loads(meta_path.read_text(encoding="utf-8"))
        trip_id = str(meta_payload["trip_id"])
        started_at = datetime.fromisoformat(str(meta_payload["started_at"]))
        sample_rate_hz = float(meta_payload["sample_rate_hz"])
    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        raise SimParseError(f"{meta_path}: unreadable meta sidecar ({exc})") from exc

    samples: list[FeatureSample] = []
    skipped = 0
    max_distance_m = 0.0
    lines = jsonl_path.read_text(encoding="utf-8").splitlines()
    for lineno, line in enumerate(lines, start=1):
        stripped = line.strip()
        if not stripped:
            continue
        try:
            payload = json.loads(stripped)
            sample, distance_m = _parse_frame(payload)
        except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
            skipped += 1
            logger.debug("%s:%d skipped: %s", jsonl_path.name, lineno, exc)
            continue
        samples.append(sample)
        max_distance_m = max(max_distance_m, distance_m)

    if skipped:
        logger.warning(
            "%s: skipped %d malformed row(s) of %d",
            jsonl_path.name,
            skipped,
            skipped + len(samples),
        )
    if not samples:
        raise SimParseError(f"{jsonl_path.name}: no usable rows after parsing")

    return SimRecording(
        meta=RecordingMeta(
            recording_id=trip_id,
            driver_id=None,
            started_at=started_at,
            sample_rate_hz=sample_rate_hz,
            distance_km=max_distance_m / 1000.0 if max_distance_m else None,
        ),
        samples=samples,
        skipped_rows=skipped,
    )


def load_recordings(paths: Iterable[Path]) -> list[SimRecording]:
    """Load several recordings, skipping any that fail rather than aborting."""
    recordings: list[SimRecording] = []
    for path in paths:
        try:
            recordings.append(load_recording(path))
        except SimParseError:
            logger.exception("skipping unreadable recording %s", path)
    return recordings
