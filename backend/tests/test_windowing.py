"""Ring-buffer and inference-tick tests.

The per-trip registry tests mirror `test_events_detectors.py`'s: same
questions (is state per trip? is it released when the trip ends?) because the
buffer is the same pattern with a different payload, and getting either wrong
leaks memory for the life of the process.

The tick tests run at a shortened interval so the suite stays fast — except
`test_a_live_trip_ticks_at_1hz_and_produces_model_output`, which deliberately
does not, because "the tick fires once a second on a real trip" is the claim
that actually needed proving and shortening the interval would prove something
else.
"""

import asyncio
import json
import time
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api.v1 import trips as trips_api
from app.core.features import FeatureSample
from app.core.live import broadcaster
from app.core.risk import sink as risk_sink
from app.core.risk.schema import Provenance, RiskBand
from app.core.windowing import buffer, ticker
from app.ml import load_model, unload_model

# The risk engine requires an artefact whose classes *are* the four risk bands
# (see `app.core.risk.score.expected_severity`), so the tick's model path is
# exercised with the band-classed fixture rather than `fixtures/model.json`,
# whose three invented class names exist to test the loader and nothing else.
FIXTURE_MODEL = Path(__file__).parent / "fixtures" / "risk" / "toy_model.json"
MODEL_CLASSES = {"CALM", "NORMAL", "AGGRESSIVE", "HIGH_RISK"}

T0 = datetime(2026, 8, 9, 10, 0, tzinfo=UTC)


def _samples(count: int, *, rate_hz: float = 10.0, start_index: int = 0) -> list[FeatureSample]:
    """Frames of plausible, varying driving so the features are not degenerate."""
    step = 1.0 / rate_hz
    return [
        FeatureSample(
            recorded_at=T0 + timedelta(seconds=(start_index + i) * step),
            speed_kph=50.0 + (i % 20),
            accel_ms2=1.5 - 0.3 * (i % 7),
            lateral_accel_ms2=0.4 * ((i % 5) - 2),
            yaw_rate_dps=2.0 * ((i % 3) - 1),
            heading_deg=float((i * 3) % 360),
        )
        for i in range(count)
    ]


@pytest.fixture(autouse=True)
def _clean_windowing_state(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """No trip's buffer, task, artefact or queued risk row may outlive its test.

    Unloads on the way *in* as well as out: any earlier test that started the
    app lifespan loaded whatever real artefact happens to sit in
    `ml/artifacts/`, and a test asserting the rule-only path must not pass or
    fail depending on whether this checkout has been trained on.

    The sink's flush bounds are raised out of reach for the duration. Most
    tests here tick against a `uuid4()` that has no `trips` row, so a flush
    would hit a foreign-key violation that says nothing about windowing. What
    the tick owes the sink is that it *enqueues*; that the sink then writes in
    batches is `test_risk_sink.py`'s subject, against real trips.
    """
    unload_model()
    risk_sink.reset()
    monkeypatch.setattr(risk_sink, "FLUSH_ROWS", 1_000_000)
    monkeypatch.setattr(risk_sink, "FLUSH_INTERVAL_S", 1_000_000.0)
    yield
    for trip_id in list(ticker._tasks):
        task = ticker._tasks.pop(trip_id)
        task.cancel()
    ticker._latest.clear()
    for trip_id in list(buffer._buffers):
        buffer.discard_trip(trip_id)
    risk_sink.reset()
    unload_model()


# --- The buffer: bounded ------------------------------------------------------


def test_buffer_is_bounded_and_drops_the_oldest_samples() -> None:
    trip_id = uuid.uuid4()

    buffer.append(trip_id, _samples(buffer.MAX_SAMPLES + 300))

    assert buffer.buffered_count(trip_id) == buffer.MAX_SAMPLES
    # The survivors are the newest ones: a dropped sample is one no tick was
    # going to read anyway, since ticks only ever look at the trailing span.
    held = buffer.buffer_for(trip_id)
    assert held[-1].recorded_at == T0 + timedelta(seconds=(buffer.MAX_SAMPLES + 299) * 0.1)
    assert held[0].recorded_at == T0 + timedelta(seconds=300 * 0.1)


def test_appending_many_batches_still_respects_the_bound() -> None:
    trip_id = uuid.uuid4()

    for batch in range(20):
        buffer.append(trip_id, _samples(100, start_index=batch * 100))

    assert buffer.buffered_count(trip_id) == buffer.MAX_SAMPLES


# --- The buffer: trailing-span snapshot ---------------------------------------


def test_snapshot_returns_only_the_trailing_span() -> None:
    trip_id = uuid.uuid4()
    buffer.append(trip_id, _samples(61, rate_hz=1.0))  # 60 seconds of 1 Hz frames

    window = buffer.snapshot(trip_id, span_s=30.0)

    assert len(window) == 30
    assert window[0].recorded_at == T0 + timedelta(seconds=31)
    assert window[-1].recorded_at == T0 + timedelta(seconds=60)


def test_snapshot_measures_the_span_from_the_newest_sample_not_from_now() -> None:
    # The buffered frames are from 2026-08-09; wall-clock now is not. A window
    # measured against now would be empty, and replayed telemetry would score
    # differently from live telemetry — the skew ADR 0004 exists to prevent.
    trip_id = uuid.uuid4()
    buffer.append(trip_id, _samples(50))

    assert len(buffer.snapshot(trip_id)) == 50


def test_snapshot_is_ordered_even_when_a_straggler_arrives_late() -> None:
    trip_id = uuid.uuid4()
    buffer.append(trip_id, _samples(10))
    late = FeatureSample(
        recorded_at=T0 + timedelta(seconds=0.55),
        speed_kph=1.0,
        accel_ms2=0.0,
        lateral_accel_ms2=0.0,
    )
    buffer.append(trip_id, [late])

    window = buffer.snapshot(trip_id)

    assert [s.recorded_at for s in window] == sorted(s.recorded_at for s in window)
    assert late in window


def test_snapshot_of_an_unknown_trip_is_empty() -> None:
    assert buffer.snapshot(uuid.uuid4()) == []


# --- The buffer: per-trip isolation and cleanup -------------------------------


def test_buffers_are_per_trip_and_do_not_mix() -> None:
    trip_a, trip_b = uuid.uuid4(), uuid.uuid4()

    buffer.append(trip_a, _samples(5))
    buffer.append(trip_b, _samples(11))

    assert buffer.buffer_for(trip_a) is not buffer.buffer_for(trip_b)
    assert buffer.buffered_count(trip_a) == 5
    assert buffer.buffered_count(trip_b) == 11


def test_discarding_one_trip_leaves_the_other_intact() -> None:
    trip_a, trip_b = uuid.uuid4(), uuid.uuid4()
    buffer.append(trip_a, _samples(5))
    buffer.append(trip_b, _samples(5))

    buffer.discard_trip(trip_a)

    assert buffer.buffered_count(trip_a) == 0
    assert buffer.buffered_count(trip_b) == 5
    assert buffer.tracked_trip_count() == 1


def test_discarding_an_unknown_trip_is_a_no_op() -> None:
    buffer.discard_trip(uuid.uuid4())

    assert buffer.tracked_trip_count() == 0


# --- The tick -----------------------------------------------------------------


async def _wait_for_tick(trip_id: uuid.UUID, *, timeout_s: float = 5.0) -> ticker.TripInference:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        latest = ticker.latest_inference(trip_id)
        if latest is not None:
            return latest
        await asyncio.sleep(0.01)
    raise AssertionError(f"no inference tick fired for {trip_id} within {timeout_s}s")


async def test_the_tick_extracts_features_without_an_artefact(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(ticker, "TICK_INTERVAL_S", 0.02)
    trip_id = uuid.uuid4()
    buffer.append(trip_id, _samples(300))

    ticker.ensure_started(trip_id, speed_limit_kph=100.0)
    latest = await _wait_for_tick(trip_id)

    # Rule-only: no model output, but the window was still reduced.
    assert latest.model_output is None
    assert latest.sample_count == 300
    assert latest.features["speed_mean"] > 0.0
    assert latest.coverage_ratio == pytest.approx(1.0)
    # And still scored. The rule layer needs no artefact, so every tick that
    # produces features produces an assessment.
    assert latest.risk.provenance is Provenance.RULES_ONLY
    assert latest.risk.model_available is False
    assert 0.0 <= latest.risk.score <= 100.0


async def test_the_tick_produces_model_output_when_an_artefact_is_loaded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(ticker, "TICK_INTERVAL_S", 0.02)
    load_model(FIXTURE_MODEL)
    trip_id = uuid.uuid4()
    buffer.append(trip_id, _samples(300))

    ticker.ensure_started(trip_id, speed_limit_kph=100.0)
    latest = await _wait_for_tick(trip_id)

    assert latest.model_output is not None
    assert latest.model_output.predicted_class in MODEL_CLASSES
    assert sum(latest.model_output.probabilities.values()) == pytest.approx(1.0)
    assert latest.risk.model_available is True
    assert latest.risk.model_band is not None
    assert latest.risk.model_version is not None


async def test_the_tick_enqueues_every_assessment_for_the_sink(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The seam between the tick and persistence: enqueue, not write."""
    monkeypatch.setattr(ticker, "TICK_INTERVAL_S", 0.02)
    trip_id = uuid.uuid4()
    buffer.append(trip_id, _samples(300))

    ticker.ensure_started(trip_id, speed_limit_kph=100.0)
    await _wait_for_tick(trip_id)

    assert risk_sink.pending_count(trip_id) >= 1
    accumulator = risk_sink.accumulator_for(trip_id)
    assert accumulator is not None
    assert accumulator.window_count >= 1


async def test_the_tick_publishes_a_risk_message_to_subscribers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """What the browser receives. Taken off the broadcaster queue the WS endpoint reads."""
    monkeypatch.setattr(ticker, "TICK_INTERVAL_S", 0.02)
    load_model(FIXTURE_MODEL)
    trip_id = uuid.uuid4()
    buffer.append(trip_id, _samples(300))
    queue = broadcaster.subscribe(trip_id)

    try:
        ticker.ensure_started(trip_id, speed_limit_kph=100.0)
        latest = await _wait_for_tick(trip_id)
        message = await asyncio.wait_for(queue.get(), timeout=2.0)
    finally:
        broadcaster.unsubscribe(trip_id, queue)

    assert message["type"] == "risk"
    data = message["data"]
    assert data["band"] == latest.risk.band.value
    assert data["score"] == pytest.approx(latest.risk.score)
    assert data["provenance"] == latest.risk.provenance.value
    assert data["risk_engine_version"] == latest.risk.risk_engine_version
    assert data["window_end"] == latest.window_end.isoformat()
    # JSON-serialisable as published, not merely as a Python object.
    json.dumps(message)


async def test_the_tick_never_emits_high_risk_without_the_rules(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ADR 0007, asserted where it actually reaches a user rather than only in the unit."""
    monkeypatch.setattr(ticker, "TICK_INTERVAL_S", 0.02)
    load_model(FIXTURE_MODEL)
    trip_id = uuid.uuid4()
    buffer.append(trip_id, _samples(300))

    ticker.ensure_started(trip_id, speed_limit_kph=100.0)
    latest = await _wait_for_tick(trip_id)

    if latest.risk.band is RiskBand.HIGH_RISK:
        assert latest.risk.rule_band is RiskBand.HIGH_RISK


async def test_a_short_window_does_not_tick_yet(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ticker, "TICK_INTERVAL_S", 0.02)
    trip_id = uuid.uuid4()
    buffer.append(trip_id, _samples(1))

    ticker.ensure_started(trip_id, speed_limit_kph=100.0)
    await asyncio.sleep(0.1)

    assert ticker.latest_inference(trip_id) is None
    assert ticker.running_trip_count() == 1  # waiting, not dead


async def test_ticks_are_per_trip(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ticker, "TICK_INTERVAL_S", 0.02)
    trip_a, trip_b = uuid.uuid4(), uuid.uuid4()
    buffer.append(trip_a, _samples(300))
    buffer.append(trip_b, _samples(50))

    ticker.ensure_started(trip_a, speed_limit_kph=100.0)
    ticker.ensure_started(trip_b, speed_limit_kph=50.0)
    latest_a = await _wait_for_tick(trip_a)
    latest_b = await _wait_for_tick(trip_b)

    assert ticker.running_trip_count() == 2
    assert latest_a.sample_count == 300
    assert latest_b.sample_count == 50


async def test_ensure_started_is_idempotent_across_batches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(ticker, "TICK_INTERVAL_S", 0.02)
    trip_id = uuid.uuid4()

    ticker.ensure_started(trip_id, speed_limit_kph=100.0)
    first = ticker._tasks[trip_id]
    for _ in range(5):
        ticker.ensure_started(trip_id, speed_limit_kph=100.0)

    assert ticker._tasks[trip_id] is first
    assert ticker.running_trip_count() == 1


async def test_the_tick_keeps_running_after_one_bad_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(ticker, "TICK_INTERVAL_S", 0.02)
    calls = {"n": 0}
    real_extract = ticker.extract_features

    def flaky(samples: list[FeatureSample], ctx: object) -> object:
        calls["n"] += 1
        if calls["n"] == 1:
            raise ValueError("simulated bad window")
        return real_extract(samples, ctx)  # type: ignore[arg-type]

    monkeypatch.setattr(ticker, "extract_features", flaky)
    trip_id = uuid.uuid4()
    buffer.append(trip_id, _samples(300))

    ticker.ensure_started(trip_id, speed_limit_kph=100.0)
    latest = await _wait_for_tick(trip_id)

    assert calls["n"] >= 2
    assert latest.tick_index >= 1


# --- Trip-end cleanup ---------------------------------------------------------


async def test_stop_trip_cancels_the_tick_and_releases_the_buffer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(ticker, "TICK_INTERVAL_S", 0.02)
    trip_id = uuid.uuid4()
    buffer.append(trip_id, _samples(300))
    ticker.ensure_started(trip_id, speed_limit_kph=100.0)
    task = ticker._tasks[trip_id]
    await _wait_for_tick(trip_id)

    await ticker.stop_trip(trip_id)

    assert task.cancelled() or task.done()
    assert ticker.running_trip_count() == 0
    assert ticker.latest_inference(trip_id) is None
    assert buffer.buffered_count(trip_id) == 0
    assert buffer.tracked_trip_count() == 0


async def test_no_tick_fires_after_the_trip_is_stopped(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ticker, "TICK_INTERVAL_S", 0.02)
    trip_id = uuid.uuid4()
    buffer.append(trip_id, _samples(300))
    ticker.ensure_started(trip_id, speed_limit_kph=100.0)
    await _wait_for_tick(trip_id)

    await ticker.stop_trip(trip_id)
    # Refill the buffer: a cancelled tick must not come back to life.
    buffer.append(trip_id, _samples(300))
    await asyncio.sleep(0.1)

    assert ticker.latest_inference(trip_id) is None


async def test_stopping_one_trip_leaves_another_ticking(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(ticker, "TICK_INTERVAL_S", 0.02)
    trip_a, trip_b = uuid.uuid4(), uuid.uuid4()
    buffer.append(trip_a, _samples(300))
    buffer.append(trip_b, _samples(300))
    ticker.ensure_started(trip_a, speed_limit_kph=100.0)
    ticker.ensure_started(trip_b, speed_limit_kph=100.0)
    await _wait_for_tick(trip_b)

    await ticker.stop_trip(trip_a)

    assert ticker.running_trip_count() == 1
    assert ticker.latest_inference(trip_b) is not None
    assert buffer.buffered_count(trip_b) == 300


async def test_stopping_an_unstarted_trip_is_a_no_op() -> None:
    await ticker.stop_trip(uuid.uuid4())

    assert ticker.running_trip_count() == 0


async def test_stop_all_tears_down_every_trip(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ticker, "TICK_INTERVAL_S", 0.02)
    for _ in range(3):
        trip_id = uuid.uuid4()
        buffer.append(trip_id, _samples(50))
        ticker.ensure_started(trip_id, speed_limit_kph=100.0)

    await ticker.stop_all()

    assert ticker.running_trip_count() == 0
    assert buffer.tracked_trip_count() == 0


# --- End to end, through the API, at the real 1 Hz ----------------------------


def _live_trip(client: TestClient, suffix: str) -> str:
    # Driver/vehicle creation requires a session; telemetry ingest below does not.
    auth = client.post(
        "/api/v1/auth/register",
        json={"email": f"windowing-{suffix}@example.com", "password": "correcthorsebattery"},
    )
    assert auth.status_code == 201, auth.text
    driver = client.post(
        "/api/v1/drivers",
        json={
            "name": "Ada Lovelace",
            "license_number": f"WIN-DRV-{suffix}",
            "date_of_birth": "1990-01-01",
        },
    )
    assert driver.status_code == 201, driver.text
    vehicle = client.post(
        "/api/v1/vehicles",
        json={
            "make": "Toyota",
            "model": "Corolla",
            "year": 2022,
            "vin": f"WINVIN00000000{suffix}",
            "license_plate": f"WIN-{suffix}",
        },
    )
    assert vehicle.status_code == 201, vehicle.text
    trip = client.post(
        "/api/v1/trips",
        json={
            "driver_id": driver.json()["id"],
            "vehicle_id": vehicle.json()["id"],
            "started_at": "2026-08-09T10:00:00Z",
            "speed_limit_kph": 100.0,
        },
    )
    assert trip.status_code == 201, trip.text
    trip_id: str = trip.json()["id"]
    return trip_id


def _post_frames(client: TestClient, trip_id: str, count: int, start_index: int = 0) -> None:
    frames = [
        {
            "schema_version": "1",
            "ts": sample.recorded_at.isoformat(),
            "speed_kph": sample.speed_kph,
            "accel_ms2": sample.accel_ms2,
            "lateral_accel_ms2": sample.lateral_accel_ms2,
            "yaw_rate_dps": sample.yaw_rate_dps,
            "heading_deg": sample.heading_deg,
        }
        for sample in _samples(count, start_index=start_index)
    ]
    response = client.post(f"/api/v1/trips/{trip_id}/telemetry/batch", json={"frames": frames})
    assert response.status_code == 201, response.text


def test_ingesting_a_batch_fills_the_trips_buffer(client: TestClient) -> None:
    trip_id = _live_trip(client, "100")

    _post_frames(client, trip_id, 40)

    assert buffer.buffered_count(uuid.UUID(trip_id)) == 40


def test_the_buffer_carries_extended_fields_the_telemetry_table_has_no_column_for(
    client: TestClient,
) -> None:
    trip_id = _live_trip(client, "110")

    _post_frames(client, trip_id, 10)

    window = buffer.snapshot(uuid.UUID(trip_id))
    assert all(sample.yaw_rate_dps is not None for sample in window)
    assert all(sample.heading_deg is not None for sample in window)


def test_a_live_trip_ticks_at_1hz_and_produces_model_output(client: TestClient) -> None:
    """The end-to-end claim: frames in over HTTP, model output out, once a second.

    Deliberately runs at the real `TICK_INTERVAL_S`. Two ticks are observed —
    the second's `tick_index` is greater than the first's — so this pins the
    *cadence*, not merely that something fired once.
    """
    load_model(FIXTURE_MODEL)
    trip_id = _live_trip(client, "200")
    _post_frames(client, trip_id, 300)  # 30 s of 10 Hz frames

    time.sleep(ticker.TICK_INTERVAL_S * 1.5)
    first = ticker.latest_inference(uuid.UUID(trip_id))
    time.sleep(ticker.TICK_INTERVAL_S)
    second = ticker.latest_inference(uuid.UUID(trip_id))

    assert first is not None, "no tick fired within 1.5s of the first batch"
    assert first.sample_count == 300
    assert first.model_output is not None
    assert first.model_output.predicted_class in MODEL_CLASSES
    assert set(first.model_output.contributions) == MODEL_CLASSES

    assert second is not None
    assert second.tick_index > first.tick_index, "the tick fired once and stopped"

    # And a risk assessment came out the far end of the same tick.
    assert first.risk.model_available is True
    assert first.risk.window_end == first.window_end
    assert first.risk.contributions, "an explained band with no contributions"


def test_ending_a_trip_stops_its_tick_and_releases_its_buffer(client: TestClient) -> None:
    trip_id = _live_trip(client, "300")
    _post_frames(client, trip_id, 50)
    assert ticker.running_trip_count() == 1

    response = client.patch(
        f"/api/v1/trips/{trip_id}",
        json={"status": "completed", "ended_at": "2026-08-09T10:30:00Z"},
    )

    assert response.status_code == 200
    assert ticker.running_trip_count() == 0
    assert buffer.buffered_count(uuid.UUID(trip_id)) == 0


def test_deleting_a_trip_releases_its_windowing_state(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Delete tears down the tick and buffer, asserted through a spy.

    Not asserted the way the trip-end test above does it, because a trip that
    has telemetry cannot be deleted at all today: `telemetry.trip_id` has no
    `ON DELETE CASCADE`, so the delete raises a ForeignKeyViolation before it
    reaches any cleanup. That is a pre-existing schema gap, unrelated to
    windowing, so this test covers the wiring that is in scope — the endpoint
    does call `stop_trip` — rather than quietly encoding the gap as expected.
    """
    stopped: list[uuid.UUID] = []
    real_stop_trip = trips_api.stop_trip

    async def spy(trip_id: uuid.UUID) -> None:
        stopped.append(trip_id)
        await real_stop_trip(trip_id)

    monkeypatch.setattr(trips_api, "stop_trip", spy)
    trip_id = _live_trip(client, "400")

    response = client.delete(f"/api/v1/trips/{trip_id}")

    assert response.status_code == 204
    assert stopped == [uuid.UUID(trip_id)]
    assert ticker.running_trip_count() == 0
    assert buffer.buffered_count(uuid.UUID(trip_id)) == 0
