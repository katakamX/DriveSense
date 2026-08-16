import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from tests.conftest import register_staff


@pytest.fixture(autouse=True)
async def _authenticated(client: TestClient, db_session: AsyncSession) -> None:
    """Driver/vehicle setup below now requires a staff session."""
    await register_staff(client, db_session, "trips-tests@example.com")


def _create_driver(client: TestClient, **overrides: object) -> dict:
    payload = {
        "name": "Ada Lovelace",
        "license_number": "TRIP-DRV-001",
        "date_of_birth": "1990-01-01",
    }
    payload.update(overrides)
    response = client.post("/api/v1/drivers", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def _create_vehicle(client: TestClient, **overrides: object) -> dict:
    payload = {
        "make": "Toyota",
        "model": "Corolla",
        "year": 2022,
        "vin": "TRIPVIN0000000001",
        "license_plate": "TRIP-001",
    }
    payload.update(overrides)
    response = client.post("/api/v1/vehicles", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def _create_trip(client: TestClient, driver_id: str, vehicle_id: str, **overrides: object) -> dict:
    payload = {
        "driver_id": driver_id,
        "vehicle_id": vehicle_id,
        "started_at": "2026-08-09T10:00:00Z",
    }
    payload.update(overrides)
    response = client.post("/api/v1/trips", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def test_create_trip(client: TestClient) -> None:
    driver = _create_driver(client, license_number="TRIP-DRV-100")
    vehicle = _create_vehicle(client, vin="TRIPVIN0000000100", license_plate="TRIP-100")

    body = _create_trip(client, driver["id"], vehicle["id"])
    assert body["driver_id"] == driver["id"]
    assert body["vehicle_id"] == vehicle["id"]
    assert body["status"] == "in_progress"
    assert body["ended_at"] is None


def test_list_trips(client: TestClient) -> None:
    driver = _create_driver(client, license_number="TRIP-DRV-200")
    vehicle = _create_vehicle(client, vin="TRIPVIN0000000200", license_plate="TRIP-200")
    _create_trip(client, driver["id"], vehicle["id"])
    _create_trip(client, driver["id"], vehicle["id"], started_at="2026-08-09T11:00:00Z")

    response = client.get("/api/v1/trips")
    assert response.status_code == 200
    assert len(response.json()) >= 2


def test_list_trips_pagination(client: TestClient) -> None:
    driver = _create_driver(client, license_number="TRIP-DRV-300")
    vehicle = _create_vehicle(client, vin="TRIPVIN0000000300", license_plate="TRIP-300")
    for i in range(3):
        _create_trip(client, driver["id"], vehicle["id"], started_at=f"2026-08-09T1{i}:00:00Z")

    response = client.get("/api/v1/trips", params={"limit": 1, "offset": 0})
    assert response.status_code == 200
    assert len(response.json()) == 1


def test_list_trips_filter_by_driver_id(client: TestClient) -> None:
    driver_a = _create_driver(client, license_number="TRIP-DRV-400")
    driver_b = _create_driver(client, license_number="TRIP-DRV-401")
    vehicle = _create_vehicle(client, vin="TRIPVIN0000000400", license_plate="TRIP-400")
    _create_trip(client, driver_a["id"], vehicle["id"])
    _create_trip(client, driver_b["id"], vehicle["id"], started_at="2026-08-09T12:00:00Z")

    response = client.get("/api/v1/trips", params={"driver_id": driver_a["id"]})
    assert response.status_code == 200
    body = response.json()
    assert all(t["driver_id"] == driver_a["id"] for t in body)
    assert len(body) == 1


def test_list_trips_filter_by_status(client: TestClient) -> None:
    driver = _create_driver(client, license_number="TRIP-DRV-500")
    vehicle = _create_vehicle(client, vin="TRIPVIN0000000500", license_plate="TRIP-500")
    completed = _create_trip(client, driver["id"], vehicle["id"])
    client.patch(f"/api/v1/trips/{completed['id']}", json={"status": "completed"})
    _create_trip(client, driver["id"], vehicle["id"], started_at="2026-08-09T13:00:00Z")

    response = client.get("/api/v1/trips", params={"status": "completed"})
    assert response.status_code == 200
    body = response.json()
    assert all(t["status"] == "completed" for t in body)
    assert len(body) == 1


def test_get_trip_by_id(client: TestClient) -> None:
    driver = _create_driver(client, license_number="TRIP-DRV-600")
    vehicle = _create_vehicle(client, vin="TRIPVIN0000000600", license_plate="TRIP-600")
    created = _create_trip(client, driver["id"], vehicle["id"])

    response = client.get(f"/api/v1/trips/{created['id']}")
    assert response.status_code == 200
    assert response.json()["id"] == created["id"]


def test_get_trip_not_found(client: TestClient) -> None:
    response = client.get("/api/v1/trips/00000000-0000-0000-0000-000000000000")
    assert response.status_code == 404


def test_update_trip(client: TestClient) -> None:
    driver = _create_driver(client, license_number="TRIP-DRV-700")
    vehicle = _create_vehicle(client, vin="TRIPVIN0000000700", license_plate="TRIP-700")
    created = _create_trip(client, driver["id"], vehicle["id"])

    response = client.patch(
        f"/api/v1/trips/{created['id']}",
        json={"status": "completed", "ended_at": "2026-08-09T10:30:00Z", "distance_km": 12.5},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "completed"
    assert body["distance_km"] == 12.5


def test_update_trip_not_found(client: TestClient) -> None:
    response = client.patch(
        "/api/v1/trips/00000000-0000-0000-0000-000000000000", json={"status": "completed"}
    )
    assert response.status_code == 404


def test_delete_trip(client: TestClient) -> None:
    driver = _create_driver(client, license_number="TRIP-DRV-800")
    vehicle = _create_vehicle(client, vin="TRIPVIN0000000800", license_plate="TRIP-800")
    created = _create_trip(client, driver["id"], vehicle["id"])

    response = client.delete(f"/api/v1/trips/{created['id']}")
    assert response.status_code == 204

    response = client.get(f"/api/v1/trips/{created['id']}")
    assert response.status_code == 404


def test_delete_trip_not_found(client: TestClient) -> None:
    response = client.delete("/api/v1/trips/00000000-0000-0000-0000-000000000000")
    assert response.status_code == 404


def test_create_trip_nonexistent_driver_conflicts(client: TestClient) -> None:
    vehicle = _create_vehicle(client, vin="TRIPVIN0000000900", license_plate="TRIP-900")

    response = client.post(
        "/api/v1/trips",
        json={
            "driver_id": "00000000-0000-0000-0000-000000000000",
            "vehicle_id": vehicle["id"],
            "started_at": "2026-08-09T10:00:00Z",
        },
    )
    assert response.status_code >= 400
