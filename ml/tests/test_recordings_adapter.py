"""Simulator JSONL adapter tests."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path

import pytest

from pipelines.adapters.recordings import SimParseError, find_recordings, load_recording

META = {
    "trip_id": "trip-a",
    "source": "simulator",
    "started_at": "2026-08-09T08:41:31.591994Z",
    "sample_rate_hz": 10.0,
    "generator": "drivesense-sim",
    "generator_version": "0.1.0",
}


def _frame(seq: int, **overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "trip_id": "trip-a",
        "seq": seq,
        "ts": datetime(2026, 8, 9, 8, 41, 31, tzinfo=UTC).isoformat(),
        "speed_kph": 40.0,
        "accel_ms2": 0.5,
        "lateral_accel_ms2": 0.1,
        "yaw_rate_dps": 1.0,
        "heading_deg": 90.0,
        "lat": 12.97,
        "lon": 77.59,
        "throttle_pct": 20.0,
        "brake_pct": 0.0,
        "gear": 3,
        "engine_rpm": 2200.0,
        "engine_load_pct": 30.0,
        "clutch_pct": 0.0,
        "distance_m": seq * 10.0,
    }
    payload.update(overrides)
    return payload


def _write_recording(
    root: Path, name: str, frames: list[dict[str, object]], meta: dict[str, object]
) -> Path:
    jsonl_path = root / f"{name}.jsonl"
    jsonl_path.write_text("\n".join(json.dumps(f) for f in frames) + "\n", encoding="utf-8")
    meta_path = root / f"{name}.meta.json"
    meta_path.write_text(json.dumps(meta), encoding="utf-8")
    return jsonl_path


def test_find_recordings_requires_a_meta_sidecar(tmp_path: Path) -> None:
    _write_recording(tmp_path, "with-meta", [_frame(0)], META)
    (tmp_path / "orphan.jsonl").write_text(json.dumps(_frame(0)) + "\n", encoding="utf-8")

    found = find_recordings(tmp_path)

    assert [p.name for p in found] == ["with-meta.jsonl"]


def test_load_recording_maps_every_core_and_extended_field(tmp_path: Path) -> None:
    path = _write_recording(tmp_path, "trip-a", [_frame(0), _frame(1)], META)

    recording = load_recording(path)

    assert recording.meta.recording_id == "trip-a"
    assert recording.meta.driver_id is None
    assert recording.meta.sample_rate_hz == 10.0
    assert len(recording.samples) == 2
    sample = recording.samples[0]
    assert sample.speed_kph == 40.0
    assert sample.lateral_accel_ms2 == 0.1
    assert sample.throttle_pct == 20.0
    assert sample.gear == 3


def test_load_recording_computes_distance_km_from_the_last_frame(tmp_path: Path) -> None:
    path = _write_recording(tmp_path, "trip-a", [_frame(0), _frame(1), _frame(2)], META)

    recording = load_recording(path)

    assert recording.meta.distance_km == pytest.approx(0.02)  # seq=2 -> distance_m=20.0


def test_malformed_rows_are_skipped_and_logged(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    frames: list[dict[str, object]] = [_frame(0), {"not": "a valid frame"}, _frame(2)]
    path = _write_recording(tmp_path, "trip-a", frames, META)

    with caplog.at_level(logging.WARNING):
        recording = load_recording(path)

    assert recording.skipped_rows == 1
    assert len(recording.samples) == 2
    assert any("skipped 1 malformed row" in r.getMessage() for r in caplog.records)


def test_load_recording_requires_the_meta_sidecar(tmp_path: Path) -> None:
    jsonl_path = tmp_path / "trip-a.jsonl"
    jsonl_path.write_text(json.dumps(_frame(0)) + "\n", encoding="utf-8")

    with pytest.raises(SimParseError, match="meta sidecar|not found"):
        load_recording(jsonl_path)


def test_load_recording_rejects_a_recording_with_no_usable_rows(tmp_path: Path) -> None:
    path = _write_recording(tmp_path, "trip-a", [{"not": "a valid frame"}], META)

    with pytest.raises(SimParseError, match="no usable rows"):
        load_recording(path)
