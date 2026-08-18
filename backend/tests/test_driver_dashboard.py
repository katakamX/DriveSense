"""Endpoint tests for the driver-facing self-service dashboard (M12)."""

from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from tests.conftest import register_staff


def _register_driver_user(client: TestClient, email: str) -> None:
    response = client.post(
        "/api/v1/auth/register", json={"email": email, "password": "correcthorsebattery"}
    )
    assert response.status_code == 201, response.text


def _create_application(client: TestClient, license_number: str) -> dict:
    response = client.post(
        "/api/v1/driver-applications",
        json={
            "name": "Dashboard Driver",
            "license_number": license_number,
            "date_of_birth": "1990-01-01",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_list_my_trips_requires_authentication(client: TestClient) -> None:
    assert client.get("/api/v1/trips/me").status_code == 401


def test_list_my_trips_404_without_a_driver_record(client: TestClient) -> None:
    _register_driver_user(client, "no-driver-record@example.com")
    response = client.get("/api/v1/trips/me")
    assert response.status_code == 404


async def test_list_my_trips_returns_only_own_trips(
    client: TestClient, db_session: AsyncSession
) -> None:
    driver_client = TestClient(client.app, raise_server_exceptions=False)
    _register_driver_user(driver_client, "dashboard-driver@example.com")
    my_application = _create_application(driver_client, "DASH-DRV-001")

    other_client = TestClient(client.app, raise_server_exceptions=False)
    _register_driver_user(other_client, "dashboard-other@example.com")
    other_application = _create_application(other_client, "DASH-DRV-002")

    staff_client = TestClient(client.app, raise_server_exceptions=False)
    await register_staff(staff_client, db_session, "dashboard-staff@example.com")
    vehicle = staff_client.post(
        "/api/v1/vehicles",
        json={
            "make": "Toyota",
            "model": "Corolla",
            "year": 2022,
            "vin": "DASHVIN0000000001",
            "license_plate": "DASH-001",
        },
    )
    assert vehicle.status_code == 201, vehicle.text
    vehicle_id = vehicle.json()["id"]

    my_trip = staff_client.post(
        "/api/v1/trips",
        json={
            "driver_id": my_application["id"],
            "vehicle_id": vehicle_id,
            "started_at": "2026-08-09T10:00:00Z",
        },
    )
    assert my_trip.status_code == 201, my_trip.text

    other_trip = staff_client.post(
        "/api/v1/trips",
        json={
            "driver_id": other_application["id"],
            "vehicle_id": vehicle_id,
            "started_at": "2026-08-09T11:00:00Z",
        },
    )
    assert other_trip.status_code == 201, other_trip.text

    response = driver_client.get("/api/v1/trips/me")
    assert response.status_code == 200, response.text
    trip_ids = {trip["id"] for trip in response.json()}
    assert trip_ids == {my_trip.json()["id"]}
