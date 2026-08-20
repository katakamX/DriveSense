"""Auth step 6: which routes the role gate covers, and which it doesn't.

Drivers, vehicles, and trips are admin/creation endpoints and now require a
*staff* session (`app.core.deps.require_staff`: logged in AND role in
{employee, admin}, applied at the router level in `app.api.v1.drivers`,
`app.api.v1.vehicles`, and `app.api.v1.trips`). A plain logged-in "user" is
refused just like an anonymous caller. Everything the simulator, the CV
process, and the browser-camera monitor talk to must keep working without
any of that: telemetry ingest, driver-state ingest, and the driver-monitor
socket.
"""

from __future__ import annotations

import base64
from typing import Any

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1 import driver_monitor as driver_monitor_route
from app.core.monitor import MonitorResult
from tests.conftest import register_staff


async def _create_trip(client: TestClient, db_session: AsyncSession, suffix: str) -> str:
    """Trip setup goes through the (now role-gated) driver/vehicle routes."""
    await register_staff(client, db_session, f"route-protection-{suffix}@example.com")
    driver = client.post(
        "/api/v1/drivers",
        json={
            "name": "Route Protection",
            "license_number": f"RP-{suffix}",
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
            "vin": f"RPVIN{suffix}".ljust(17, "0")[:17],
            "license_plate": f"RP-{suffix}"[:20],
        },
    )
    assert vehicle.status_code == 201, vehicle.text
    trip = client.post(
        "/api/v1/trips",
        json={
            "driver_id": driver.json()["id"],
            "vehicle_id": vehicle.json()["id"],
            "started_at": "2026-08-09T10:00:00Z",
        },
    )
    assert trip.status_code == 201, trip.text
    return str(trip.json()["id"])


# --- newly protected: drivers and vehicles --------------------------------


def test_list_drivers_requires_authentication(client: TestClient) -> None:
    assert client.get("/api/v1/drivers").status_code == 401


def test_create_driver_requires_authentication(client: TestClient) -> None:
    response = client.post(
        "/api/v1/drivers",
        json={"name": "No Session", "license_number": "RP-NOAUTH", "date_of_birth": "1990-01-01"},
    )
    assert response.status_code == 401


def test_list_vehicles_requires_authentication(client: TestClient) -> None:
    assert client.get("/api/v1/vehicles").status_code == 401


def test_create_vehicle_requires_authentication(client: TestClient) -> None:
    response = client.post(
        "/api/v1/vehicles",
        json={
            "make": "Test",
            "model": "Rig",
            "year": 2021,
            "vin": "RPNOAUTHVIN000001",
            "license_plate": "RP-NOAUTH",
        },
    )
    assert response.status_code == 401


def test_list_trips_requires_authentication(client: TestClient) -> None:
    assert client.get("/api/v1/trips").status_code == 401


def test_obd_analyze_requires_authentication(client: TestClient) -> None:
    files = {"file": ("t.csv", b"Time_s,Speed_kmh\n0.03,0.0\n", "text/csv")}
    response = client.post("/api/v1/obd/analyze", files=files)
    assert response.status_code == 401


def test_create_trip_requires_authentication(client: TestClient) -> None:
    response = client.post(
        "/api/v1/trips",
        json={
            "driver_id": "00000000-0000-0000-0000-000000000000",
            "vehicle_id": "00000000-0000-0000-0000-000000000000",
            "started_at": "2026-08-09T10:00:00Z",
        },
    )
    assert response.status_code == 401


# --- logged in, but not staff: also refused --------------------------------


def test_create_driver_refuses_plain_user_role(client: TestClient) -> None:
    response = client.post(
        "/api/v1/auth/register",
        json={"email": "plain-user@example.com", "password": "correcthorsebattery"},
    )
    assert response.status_code == 201, response.text
    assert response.json()["role"] == "user"

    response = client.post(
        "/api/v1/drivers",
        json={"name": "Plain User", "license_number": "RP-PLAIN", "date_of_birth": "1990-01-01"},
    )
    assert response.status_code == 403


def test_create_vehicle_refuses_plain_user_role(client: TestClient) -> None:
    client.post(
        "/api/v1/auth/register",
        json={"email": "plain-user-2@example.com", "password": "correcthorsebattery"},
    )

    response = client.post(
        "/api/v1/vehicles",
        json={
            "make": "Test",
            "model": "Rig",
            "year": 2021,
            "vin": "RPPLAINVIN0000001",
            "license_plate": "RP-PLAIN",
        },
    )
    assert response.status_code == 403


def test_list_trips_refuses_plain_user_role(client: TestClient) -> None:
    client.post(
        "/api/v1/auth/register",
        json={"email": "plain-user-3@example.com", "password": "correcthorsebattery"},
    )

    response = client.get("/api/v1/trips")
    assert response.status_code == 403


def test_obd_analyze_refuses_plain_user_role(client: TestClient) -> None:
    client.post(
        "/api/v1/auth/register",
        json={"email": "plain-user-4@example.com", "password": "correcthorsebattery"},
    )

    files = {"file": ("t.csv", b"Time_s,Speed_kmh\n0.03,0.0\n", "text/csv")}
    response = client.post("/api/v1/obd/analyze", files=files)
    assert response.status_code == 403


# --- left alone: simulator / CV process / browser-camera monitor ----------


async def test_telemetry_batch_ingest_still_works_without_authentication(
    client: TestClient, db_session: AsyncSession
) -> None:
    trip_id = await _create_trip(client, db_session, "TEL01")
    unauth_client = TestClient(client.app, raise_server_exceptions=False)

    response = unauth_client.post(
        f"/api/v1/trips/{trip_id}/telemetry/batch",
        json={
            "frames": [
                {
                    "schema_version": "1",
                    "ts": "2026-08-09T10:00:01Z",
                    "speed_kph": 50.0,
                    "accel_ms2": 0.0,
                    "lateral_accel_ms2": 0.0,
                }
            ]
        },
    )
    assert response.status_code == 201, response.text


async def test_driver_state_ingest_still_works_without_authentication(
    client: TestClient, db_session: AsyncSession
) -> None:
    trip_id = await _create_trip(client, db_session, "TEL02")
    unauth_client = TestClient(client.app, raise_server_exceptions=False)

    response = unauth_client.post(
        "/api/v1/ingest/driver-state",
        json={
            "schema_version": "1",
            "trip_id": trip_id,
            "ts": "2026-08-09T10:00:01Z",
            "face_detected": True,
        },
    )
    assert response.status_code == 201, response.text


def test_driver_monitor_socket_still_works_without_authentication(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    class FakeMonitorSession:
        def __init__(self) -> None:
            self.closed = False

        def observe(self, frame_bgr: Any, now_s: float) -> MonitorResult:
            return MonitorResult(
                face_detected=True,
                not_visible=False,
                ear=0.30,
                mar=0.10,
                eyes_closed=False,
                drowsy=False,
                yawning=False,
            )

        def close(self) -> None:
            self.closed = True

    monkeypatch.setattr(driver_monitor_route, "MonitorSession", FakeMonitorSession)

    ok, buffer = cv2.imencode(".jpg", np.zeros((8, 8, 3), dtype=np.uint8))
    assert ok
    frame = "data:image/jpeg;base64," + base64.b64encode(buffer.tobytes()).decode()

    with client.websocket_connect("/api/v1/ws/driver-monitor/DRV-NOAUTH") as socket:
        socket.send_json({"frame": frame})
        message = socket.receive_json()

    assert message["type"] == "reading"
