"""Auth step 6: which routes the login-required gate covers, and which it doesn't.

Drivers and vehicles are admin/creation/review endpoints and now require a
session (`app.core.deps.get_current_user`, applied at the router level in
`app.api.v1.drivers` and `app.api.v1.vehicles`). Everything the simulator, the
CV process, and the browser-camera monitor talk to must keep working without
one: telemetry ingest, driver-state ingest, and the driver-monitor socket.
"""

from __future__ import annotations

import base64
from typing import Any

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

from app.api.v1 import driver_monitor as driver_monitor_route
from app.core.monitor import MonitorResult


def _register(client: TestClient, email: str) -> None:
    response = client.post(
        "/api/v1/auth/register", json={"email": email, "password": "correcthorsebattery"}
    )
    assert response.status_code == 201, response.text


def _create_trip(client: TestClient, suffix: str) -> str:
    """Trip setup goes through the (now-protected) driver/vehicle routes."""
    _register(client, f"route-protection-{suffix}@example.com")
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


# --- left alone: simulator / CV process / browser-camera monitor ----------


def test_telemetry_batch_ingest_still_works_without_authentication(client: TestClient) -> None:
    trip_id = _create_trip(client, "TEL01")
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


def test_driver_state_ingest_still_works_without_authentication(client: TestClient) -> None:
    trip_id = _create_trip(client, "TEL02")
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
