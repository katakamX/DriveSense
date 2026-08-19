"""Endpoint tests for trip detail sub-resources (M12 page 2): staff can view
any trip, a driver can view their own trip, and a driver reading another
driver's trip gets the same 404 a nonexistent trip would (not 403)."""

from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import DrivingEvent, RiskWindow, Telemetry
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
            "name": "Detail Driver",
            "license_number": license_number,
            "date_of_birth": "1990-01-01",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


async def _seed_trip(
    staff_client: TestClient, db_session: AsyncSession, driver_id: str, vin: str, plate: str
) -> str:
    vehicle = staff_client.post(
        "/api/v1/vehicles",
        json={
            "make": "Toyota",
            "model": "Corolla",
            "year": 2022,
            "vin": vin,
            "license_plate": plate,
        },
    )
    assert vehicle.status_code == 201, vehicle.text

    trip = staff_client.post(
        "/api/v1/trips",
        json={
            "driver_id": driver_id,
            "vehicle_id": vehicle.json()["id"],
            "started_at": "2026-08-09T10:00:00Z",
        },
    )
    assert trip.status_code == 201, trip.text
    trip_id = trip.json()["id"]

    telemetry = Telemetry(
        trip_id=trip_id,
        recorded_at="2026-08-09T10:00:05Z",
        schema_version="1",
        speed_kph=50.0,
        accel_ms2=0.5,
        lateral_accel_ms2=0.1,
        lat=1.23,
        lon=4.56,
        raw_frame={},
    )
    db_session.add(telemetry)
    await db_session.flush()
    db_session.add(
        DrivingEvent(
            trip_id=trip_id,
            telemetry_id=telemetry.id,
            event_type="harsh_brake",
            occurred_at="2026-08-09T10:00:05Z",
            measured_value=-4.5,
            threshold_value=-3.5,
        )
    )
    db_session.add(
        RiskWindow(
            trip_id=trip_id,
            window_start="2026-08-09T10:00:00Z",
            window_end="2026-08-09T10:00:30Z",
            sample_count=30,
            coverage_ratio=1.0,
            score=42.0,
            band="medium",
            confidence=0.9,
            provenance="rule_only",
            model_available=False,
            gated=False,
            rule_band="medium",
            matched_rules=["harsh_brake"],
            model_band=None,
            model_score=None,
            model_predicted_class=None,
            probabilities=None,
            contributions=None,
            contributions_remainder=None,
            risk_engine_version="1",
            feature_version="1",
            rubric_version="1",
            model_version=None,
        )
    )
    await db_session.commit()
    return trip_id


async def test_requires_authentication(client: TestClient, db_session: AsyncSession) -> None:
    await register_staff(client, db_session, "detail-setup@example.com")
    driver = client.post(
        "/api/v1/drivers",
        json={"name": "A", "license_number": "DETAIL-001", "date_of_birth": "1990-01-01"},
    )
    trip_id = await _seed_trip(client, db_session, driver.json()["id"], "DETAILVIN001", "DTL-001")

    anon = TestClient(client.app, raise_server_exceptions=False)
    assert anon.get(f"/api/v1/trips/{trip_id}/risk-windows").status_code == 401
    assert anon.get(f"/api/v1/trips/{trip_id}/events").status_code == 401
    assert anon.get(f"/api/v1/trips/{trip_id}/telemetry").status_code == 401


async def test_staff_can_view_any_trip_detail(client: TestClient, db_session: AsyncSession) -> None:
    await register_staff(client, db_session, "detail-staff@example.com")
    driver = client.post(
        "/api/v1/drivers",
        json={"name": "B", "license_number": "DETAIL-002", "date_of_birth": "1990-01-01"},
    )
    trip_id = await _seed_trip(client, db_session, driver.json()["id"], "DETAILVIN002", "DTL-002")

    risk_windows = client.get(f"/api/v1/trips/{trip_id}/risk-windows")
    assert risk_windows.status_code == 200, risk_windows.text
    assert len(risk_windows.json()) == 1

    events = client.get(f"/api/v1/trips/{trip_id}/events")
    assert events.status_code == 200, events.text
    assert len(events.json()) == 1

    telemetry = client.get(f"/api/v1/trips/{trip_id}/telemetry")
    assert telemetry.status_code == 200, telemetry.text
    assert len(telemetry.json()) == 1


async def test_driver_can_view_own_trip_detail(
    client: TestClient, db_session: AsyncSession
) -> None:
    driver_client = TestClient(client.app, raise_server_exceptions=False)
    _register_driver_user(driver_client, "detail-driver-own@example.com")
    application = _create_application(driver_client, "DETAIL-DRV-001")

    staff_client = TestClient(client.app, raise_server_exceptions=False)
    await register_staff(staff_client, db_session, "detail-staff-2@example.com")
    trip_id = await _seed_trip(
        staff_client, db_session, application["id"], "DETAILVIN003", "DTL-003"
    )

    response = driver_client.get(f"/api/v1/trips/{trip_id}/risk-windows")
    assert response.status_code == 200, response.text
    assert len(response.json()) == 1


async def test_driver_cannot_view_other_drivers_trip_detail(
    client: TestClient, db_session: AsyncSession
) -> None:
    owner_client = TestClient(client.app, raise_server_exceptions=False)
    _register_driver_user(owner_client, "detail-driver-owner@example.com")
    owner_application = _create_application(owner_client, "DETAIL-DRV-002")

    other_client = TestClient(client.app, raise_server_exceptions=False)
    _register_driver_user(other_client, "detail-driver-other@example.com")

    staff_client = TestClient(client.app, raise_server_exceptions=False)
    await register_staff(staff_client, db_session, "detail-staff-3@example.com")
    trip_id = await _seed_trip(
        staff_client, db_session, owner_application["id"], "DETAILVIN004", "DTL-004"
    )

    response = other_client.get(f"/api/v1/trips/{trip_id}/risk-windows")
    assert response.status_code == 404


async def test_nonexistent_trip_is_404_for_staff(
    client: TestClient, db_session: AsyncSession
) -> None:
    await register_staff(client, db_session, "detail-staff-4@example.com")
    response = client.get("/api/v1/trips/00000000-0000-0000-0000-000000000000/risk-windows")
    assert response.status_code == 404
