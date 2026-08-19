"""`HttpSink` — batching, failure accounting, and payload shape.

Every test drives a `httpx.MockTransport`, so nothing here opens a socket. The
one thing a mock cannot check is that the backend accepts the payload; that is
covered by the backend's own `test_telemetry.py` and by the live run recorded
in `docs/m14-benchmark.md`.
"""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest

from drivesense_contracts import SCHEMA_VERSION, TelemetryFrame, TelemetrySink, TripMeta
from drivesense_sim.telemetry.sinks import HttpSink

TRIP_ID = "3f1c0a4e-2b7d-4a55-9e10-6c8b1d2f4a90"
STARTED_AT = datetime(2026, 3, 1, 9, 0, tzinfo=UTC)


def make_frame(seq: int) -> TelemetryFrame:
    return TelemetryFrame(
        trip_id="sim-bench",
        source="simulator",
        seq=seq,
        sim_t=seq * 0.1,
        ts=STARTED_AT,
        speed_kph=42.0,
        accel_ms2=0.5,
        engine_rpm=2100.0,
        throttle_pct=30.0,
        brake_pct=0.0,
        clutch_pct=0.0,
        gear=3,
        engine_load_pct=40.0,
        steering_deg=1.0,
        yaw_rate_dps=0.2,
        lateral_accel_ms2=0.1,
        heading_deg=90.0,
        distance_m=seq * 1.2,
        lat=12.97,
        lon=77.59,
    )


def make_meta() -> TripMeta:
    return TripMeta(
        trip_id="sim-bench",
        source="simulator",
        started_at=STARTED_AT,
        sample_rate_hz=10.0,
        generator="drivesense-sim",
        generator_version="0.1.0",
    )


class Recorder:
    """Captures every request the sink makes and replies with `status`."""

    def __init__(self, status: int = 201, body: Any = None) -> None:
        self.status = status
        self.body = body if body is not None else {"accepted": 0}
        self.requests: list[httpx.Request] = []
        self.payloads: list[dict[str, Any]] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        self.payloads.append(json.loads(request.read()))
        return httpx.Response(self.status, json=self.body)

    def sink(self, **kwargs: Any) -> HttpSink:
        transport = httpx.MockTransport(self)
        client = httpx.Client(transport=transport, base_url="http://backend")
        return HttpSink("http://backend", TRIP_ID, client=client, **kwargs)


def test_conforms_to_the_sink_protocol() -> None:
    assert isinstance(Recorder().sink(), TelemetrySink)


def test_posts_a_batch_once_the_buffer_fills() -> None:
    recorder = Recorder()
    sink = recorder.sink(batch_size=3)
    sink.open(make_meta())

    for seq in range(2):
        sink.write(make_frame(seq))
    assert recorder.requests == [], "posted before the batch was full"

    sink.write(make_frame(2))
    assert len(recorder.requests) == 1
    assert sink.frames_sent == 3
    assert sink.batches_sent == 1


def test_close_flushes_a_partial_batch() -> None:
    recorder = Recorder()
    sink = recorder.sink(batch_size=10)
    sink.open(make_meta())
    for seq in range(4):
        sink.write(make_frame(seq))
    assert recorder.requests == []

    sink.close()

    assert len(recorder.requests) == 1
    assert len(recorder.payloads[0]["frames"]) == 4
    assert sink.frames_sent == 4


def test_close_with_nothing_buffered_sends_no_request() -> None:
    """The endpoint's `frames` list is `min_length=1`, so an empty flush would
    be a guaranteed 422 rather than a harmless no-op."""
    recorder = Recorder()
    sink = recorder.sink(batch_size=10)
    sink.open(make_meta())
    sink.close()
    assert recorder.requests == []


def test_posts_to_the_backend_trip_not_the_recording_id() -> None:
    recorder = Recorder()
    sink = recorder.sink(batch_size=1)
    sink.open(make_meta())
    sink.write(make_frame(0))

    url = str(recorder.requests[0].url)
    assert url == f"http://backend/api/v1/trips/{TRIP_ID}/telemetry/batch"
    assert "sim-bench" not in url


def test_payload_carries_the_fields_the_backend_reads() -> None:
    recorder = Recorder()
    sink = recorder.sink(batch_size=1)
    sink.open(make_meta())
    sink.write(make_frame(7))

    frame = recorder.payloads[0]["frames"][0]
    assert frame["schema_version"] == SCHEMA_VERSION
    for field in ("ts", "speed_kph", "accel_ms2", "lateral_accel_ms2", "lat", "lon"):
        assert field in frame, f"{field} missing from the posted frame"
    # Extended fields the ingest endpoint pulls off the payload for feature
    # extraction (`_optional_float` in app/api/v1/telemetry.py). They are not
    # columns on the telemetry table, so only the raw payload carries them.
    assert frame["yaw_rate_dps"] == pytest.approx(0.2)
    assert frame["heading_deg"] == pytest.approx(90.0)


def test_error_status_is_counted_and_does_not_raise() -> None:
    recorder = Recorder(status=404, body={"detail": "Trip not found"})
    sink = recorder.sink(batch_size=2)
    sink.open(make_meta())
    sink.write(make_frame(0))
    sink.write(make_frame(1))

    assert sink.frames_failed == 2
    assert sink.batches_failed == 1
    assert sink.frames_sent == 0


def test_transport_failure_is_counted_and_does_not_raise() -> None:
    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    client = httpx.Client(transport=httpx.MockTransport(refuse), base_url="http://backend")
    sink = HttpSink("http://backend", TRIP_ID, batch_size=1, client=client)
    sink.open(make_meta())
    sink.write(make_frame(0))

    assert sink.frames_failed == 1
    assert sink.frames_sent == 0


def test_a_failed_batch_does_not_stall_the_ones_after_it() -> None:
    """A run that gave up after the first blip would under-report throughput as
    badly as one that hid the blip entirely."""
    calls = {"n": 0}

    def flaky(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(500 if calls["n"] == 1 else 201, json={"accepted": 1})

    client = httpx.Client(transport=httpx.MockTransport(flaky), base_url="http://backend")
    sink = HttpSink("http://backend", TRIP_ID, batch_size=1, client=client)
    sink.open(make_meta())
    for seq in range(3):
        sink.write(make_frame(seq))

    assert sink.frames_failed == 1
    assert sink.frames_sent == 2


def test_sent_at_records_wall_clock_time_per_frame_on_success() -> None:
    recorder = Recorder()
    sink = recorder.sink(batch_size=2)
    sink.open(make_meta())
    before = time.time()
    sink.write(make_frame(0))
    sink.write(make_frame(1))
    after = time.time()

    assert set(sink.sent_at) == {0, 1}
    for sent in sink.sent_at.values():
        assert before <= sent <= after


def test_sent_at_omits_frames_from_a_failed_batch() -> None:
    recorder = Recorder(status=500)
    sink = recorder.sink(batch_size=1)
    sink.open(make_meta())
    sink.write(make_frame(0))

    assert sink.sent_at == {}


def test_open_resets_counters_between_runs() -> None:
    recorder = Recorder()
    sink = recorder.sink(batch_size=1)
    sink.open(make_meta())
    sink.write(make_frame(0))
    assert sink.frames_sent == 1

    sink.open(make_meta())

    assert sink.frames_sent == 0
    assert sink.batches_sent == 0
    assert sink.sent_at == {}


def test_rejects_a_nonsense_batch_size() -> None:
    with pytest.raises(ValueError, match="batch_size"):
        HttpSink("http://backend", TRIP_ID, batch_size=0)
