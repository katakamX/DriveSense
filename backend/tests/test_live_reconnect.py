"""The live socket's connection lifecycle: what it says, and when it lets go.

Two failures live here, and only one of them is visible from the browser.

The visible one is the empty page: a client that connects between pushes used
to be told nothing at all and had to wait for the pipeline to speak. The
invisible one is the leak: the old relay never read from the socket, so a
client that went away was never noticed and its subscriber queue stayed in the
broadcaster for the life of the process. Nothing about that is observable from
the outside — which is why `subscriber_count` is asserted directly rather than
inferred from behaviour.

## Why every socket here is closed by hand

`TestClient` tears a session down by sending the disconnect and then cancelling
the ASGI task, back to back, without waiting for the endpoint in between. An
endpoint that has not finished by then is simply killed — which for these tests
would mean racing the exact code under examination, and passing or failing on
scheduler timing. So each test closes its socket explicitly and waits for the
server to let go before leaving the block, and `live_socket` is the only place
that has to know it.
"""

from __future__ import annotations

import contextlib
import time
import uuid
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.testclient import WebSocketTestSession
from starlette.websockets import WebSocketDisconnect

from app.api.v1 import live as live_route
from app.core.live import broadcaster, publish
from app.core.risk import sink as risk_sink
from app.core.windowing import buffer
from tests.conftest import register_staff

TRIP_START = "2026-08-11T09:00:00Z"

# Generous: it bounds a failure, not the normal path, which settles in a
# millisecond or two.
RELEASE_TIMEOUT_S = 3.0


async def _make_trip(client: TestClient, db_session: AsyncSession, suffix: str) -> str:
    # Driver/vehicle creation requires a staff session; the live socket and
    # telemetry ingest exercised elsewhere in this file do not.
    await register_staff(client, db_session, f"live-{suffix}@example.com")
    driver = client.post(
        "/api/v1/drivers",
        json={
            "name": "Live Reconnect",
            "license_number": f"LIVE-{suffix}",
            "date_of_birth": "1990-01-01",
        },
    )
    assert driver.status_code == 201, driver.text
    vehicle = client.post(
        "/api/v1/vehicles",
        json={
            "make": "Test",
            "model": "Rig",
            "year": 2021,
            "vin": f"LIVEVIN{suffix}".ljust(17, "0")[:17],
            "license_plate": f"LV-{suffix}"[:20],
        },
    )
    assert vehicle.status_code == 201, vehicle.text
    trip = client.post(
        "/api/v1/trips",
        json={
            "driver_id": driver.json()["id"],
            "vehicle_id": vehicle.json()["id"],
            "started_at": TRIP_START,
            "speed_limit_kph": 50.0,
        },
    )
    assert trip.status_code == 201, trip.text
    return str(trip.json()["id"])


@pytest.fixture(autouse=True)
def _clean_live_state() -> Iterator[None]:
    """Per-trip pipeline state is module-level, so it outlives the test that made it."""
    risk_sink.reset()
    yield
    risk_sink.reset()


def wait_for_subscribers(trip_id: uuid.UUID, expected: int) -> int:
    """Block until the broadcaster holds `expected` queues for the trip, or give up.

    The server runs on the portal's thread, so this polls rather than awaits.
    Returns the count it settled on, so a caller can assert on it and get the
    real number in the failure message instead of a bare timeout.
    """
    deadline = time.monotonic() + RELEASE_TIMEOUT_S
    while broadcaster.subscriber_count(trip_id) != expected and time.monotonic() < deadline:
        time.sleep(0.005)
    # `unsubscribe` runs in the endpoint's `finally`, a step before the endpoint
    # itself returns and its dependencies are torn down. The count reaching
    # zero means the relay has let go, not that the task is gone — so give the
    # rest of the teardown a moment before the caller cancels it.
    time.sleep(0.05)
    return broadcaster.subscriber_count(trip_id)


@contextlib.contextmanager
def live_socket(
    client: TestClient, trip_id: str
) -> Iterator[tuple[WebSocketTestSession, dict[str, Any]]]:
    """A connected socket and its snapshot, closed cleanly on the way out.

    The snapshot is consumed here because it is unconditionally the first
    message: a test that wanted the second one would otherwise have to open
    with a discard, and a test that forgot would assert against the wrong
    frame.
    """
    key = uuid.UUID(trip_id)
    with client.websocket_connect(f"/api/v1/trips/{trip_id}/live") as socket:
        message = socket.receive_json()
        assert message["type"] == "snapshot", message
        # Counted only now: `subscribe` happens between `accept` and this
        # message, so receiving it is what makes the count meaningful.
        held = broadcaster.subscriber_count(key)
        try:
            yield socket, message["data"]
        finally:
            socket.close(1000)
            wait_for_subscribers(key, held - 1)


def _post_frames(client: TestClient, trip_id: str, frames: list[dict[str, object]]) -> None:
    response = client.post(f"/api/v1/trips/{trip_id}/telemetry/batch", json={"frames": frames})
    assert response.status_code == 201, response.text


# --- the snapshot -------------------------------------------------------------


async def test_an_untouched_trip_snapshots_empty_rather_than_absent(
    client: TestClient, db_session: AsyncSession
) -> None:
    """A restart leaves the server with nothing, and it must say so in the schema's shape.

    The client branches on three nullable facts; it must never have to branch on
    whether a snapshot arrived at all.
    """
    trip_id = await _make_trip(client, db_session, "SNAP02")

    with live_socket(client, trip_id) as (_, snapshot):
        assert set(snapshot) == {"telemetry", "risk", "events"}
        assert snapshot["telemetry"] is None
        assert snapshot["risk"] is None
        assert snapshot["events"] == []


async def test_the_snapshot_carries_the_newest_buffered_frame(
    client: TestClient, db_session: AsyncSession
) -> None:
    trip_id = await _make_trip(client, db_session, "SNAP03")
    _post_frames(
        client,
        trip_id,
        [
            {
                "schema_version": "1",
                "ts": "2026-08-11T09:00:00Z",
                "speed_kph": 40.0,
                "accel_ms2": 0.4,
                "lateral_accel_ms2": 0.1,
            },
            {
                "schema_version": "1",
                "ts": "2026-08-11T09:00:01Z",
                "speed_kph": 44.0,
                "accel_ms2": 0.6,
                "lateral_accel_ms2": 0.2,
            },
        ],
    )
    try:
        with live_socket(client, trip_id) as (_, snapshot):
            telemetry = snapshot["telemetry"]
            assert telemetry is not None
            assert telemetry["speed_kph"] == 44.0
            # The same keys a pushed `telemetry` message carries, so the client
            # applies both through one code path.
            assert set(telemetry) == {
                "recorded_at",
                "speed_kph",
                "accel_ms2",
                "lateral_accel_ms2",
                "lat",
                "lon",
            }
    finally:
        buffer.discard_trip(uuid.UUID(trip_id))


async def test_the_snapshot_replays_events_the_client_missed(
    client: TestClient, db_session: AsyncSession
) -> None:
    """Events are written before they are published, so the table is not a guess.

    This is the one part of a reconnect that genuinely recovers lost data rather
    than merely resuming from what the client already had.
    """
    trip_id = await _make_trip(client, db_session, "SNAP04")
    # A hard stop from 60 km/h, finished inside the batch so the detector emits
    # it here rather than holding it open for a later one.
    _post_frames(
        client,
        trip_id,
        [
            {
                "schema_version": "1",
                "ts": f"2026-08-11T09:00:0{index}Z",
                "speed_kph": speed,
                "accel_ms2": accel,
                "lateral_accel_ms2": 0.1,
            }
            for index, (speed, accel) in enumerate(
                [(60.0, 0.0), (45.0, -5.5), (30.0, -5.5), (28.0, 0.0), (28.0, 0.0)]
            )
        ],
    )
    try:
        with live_socket(client, trip_id) as (_, snapshot):
            events = snapshot["events"]
            assert len(events) >= 1
            assert set(events[0]) == {
                "event_type",
                "occurred_at",
                "measured_value",
                "threshold_value",
            }
    finally:
        buffer.discard_trip(uuid.UUID(trip_id))


def test_a_missing_trip_is_refused_before_the_socket_opens(client: TestClient) -> None:
    """4404 is terminal on the client side, so it must not be reachable by accident."""
    with (
        pytest.raises(WebSocketDisconnect) as caught,
        client.websocket_connect(f"/api/v1/trips/{uuid.uuid4()}/live") as socket,
    ):
        socket.receive_json()

    assert caught.value.code == 4404


# --- the relay ----------------------------------------------------------------


async def test_published_messages_still_reach_the_socket(
    client: TestClient, db_session: AsyncSession
) -> None:
    """The three-task rewrite must not have cost the endpoint its actual job."""
    trip_id = await _make_trip(client, db_session, "RELAY1")

    with live_socket(client, trip_id) as (socket, _):
        publish(uuid.UUID(trip_id), {"type": "risk", "data": {"score": 42.0}})
        message = socket.receive_json()

    assert message["type"] == "risk"
    assert message["data"]["score"] == 42.0


async def test_the_heartbeat_speaks_on_an_idle_trip(
    client: TestClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Nothing is being published; the socket must still prove it is alive."""
    monkeypatch.setattr(live_route, "PING_INTERVAL_S", 0.05)
    trip_id = await _make_trip(client, db_session, "PING01")

    with live_socket(client, trip_id) as (socket, _):
        message = socket.receive_json()

    assert message["type"] == "ping"
    assert "sent_at" in message["data"]


# --- letting go ---------------------------------------------------------------


async def test_a_disconnect_releases_the_subscriber_queue(
    client: TestClient, db_session: AsyncSession
) -> None:
    """The leak. Without a reader task, this count stays at 1 for the process's life.

    Idle on purpose: the old relay did eventually notice a disconnect when a
    send failed, so a test that published first could have passed against the
    very bug it exists to catch.
    """
    trip_id = await _make_trip(client, db_session, "LEAK01")
    key = uuid.UUID(trip_id)

    with client.websocket_connect(f"/api/v1/trips/{trip_id}/live") as socket:
        assert socket.receive_json()["type"] == "snapshot"
        assert broadcaster.subscriber_count(key) == 1
        socket.close(1000)
        assert wait_for_subscribers(key, 0) == 0


async def test_repeated_connect_and_drop_cycles_leave_nothing_behind(
    client: TestClient, db_session: AsyncSession
) -> None:
    """A reconnecting client opens one socket per attempt, and the backoff makes several."""
    trip_id = await _make_trip(client, db_session, "LEAK02")
    key = uuid.UUID(trip_id)

    for _ in range(4):
        with live_socket(client, trip_id):
            pass

    assert broadcaster.subscriber_count(key) == 0


async def test_two_clients_on_one_trip_are_tracked_and_released_separately(
    client: TestClient, db_session: AsyncSession
) -> None:
    trip_id = await _make_trip(client, db_session, "LEAK03")
    key = uuid.UUID(trip_id)

    with live_socket(client, trip_id):
        with live_socket(client, trip_id):
            assert broadcaster.subscriber_count(key) == 2
        assert broadcaster.subscriber_count(key) == 1

    assert broadcaster.subscriber_count(key) == 0
