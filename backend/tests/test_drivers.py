import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from tests.conftest import register_staff


@pytest.fixture(autouse=True)
async def _authenticated(client: TestClient, db_session: AsyncSession) -> None:
    await register_staff(client, db_session, "drivers-tests@example.com")


def _create_driver(client: TestClient, **overrides: object) -> dict:
    payload = {
        "name": "Ada Lovelace",
        "license_number": "LN-001",
        "date_of_birth": "1990-01-01",
    }
    payload.update(overrides)
    response = client.post("/api/v1/drivers", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def test_create_driver(client: TestClient) -> None:
    body = _create_driver(client)
    assert body["name"] == "Ada Lovelace"
    assert body["license_number"] == "LN-001"
    assert "id" in body
    assert "created_at" in body


def test_list_drivers(client: TestClient) -> None:
    _create_driver(client, license_number="LN-100")
    _create_driver(client, license_number="LN-101")

    response = client.get("/api/v1/drivers")
    assert response.status_code == 200
    body = response.json()
    assert len(body) >= 2


def test_list_drivers_pagination(client: TestClient) -> None:
    for i in range(3):
        _create_driver(client, license_number=f"LN-20{i}")

    response = client.get("/api/v1/drivers", params={"limit": 1, "offset": 0})
    assert response.status_code == 200
    assert len(response.json()) == 1


def test_list_drivers_filter_by_name(client: TestClient) -> None:
    _create_driver(client, name="Grace Hopper", license_number="LN-300")
    _create_driver(client, name="Ada Lovelace", license_number="LN-301")

    response = client.get("/api/v1/drivers", params={"name": "Grace Hopper"})
    assert response.status_code == 200
    body = response.json()
    assert all(d["name"] == "Grace Hopper" for d in body)
    assert len(body) == 1


def test_get_driver_by_id(client: TestClient) -> None:
    created = _create_driver(client, license_number="LN-400")

    response = client.get(f"/api/v1/drivers/{created['id']}")
    assert response.status_code == 200
    assert response.json()["id"] == created["id"]


def test_get_driver_not_found(client: TestClient) -> None:
    response = client.get("/api/v1/drivers/00000000-0000-0000-0000-000000000000")
    assert response.status_code == 404


def test_update_driver(client: TestClient) -> None:
    created = _create_driver(client, license_number="LN-500")

    response = client.patch(f"/api/v1/drivers/{created['id']}", json={"name": "New Name"})
    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "New Name"
    assert body["license_number"] == "LN-500"


def test_update_driver_not_found(client: TestClient) -> None:
    response = client.patch(
        "/api/v1/drivers/00000000-0000-0000-0000-000000000000", json={"name": "X"}
    )
    assert response.status_code == 404


def test_delete_driver(client: TestClient) -> None:
    created = _create_driver(client, license_number="LN-600")

    response = client.delete(f"/api/v1/drivers/{created['id']}")
    assert response.status_code == 204

    response = client.get(f"/api/v1/drivers/{created['id']}")
    assert response.status_code == 404


def test_delete_driver_not_found(client: TestClient) -> None:
    response = client.delete("/api/v1/drivers/00000000-0000-0000-0000-000000000000")
    assert response.status_code == 404


def test_create_driver_duplicate_license_number_conflicts(client: TestClient) -> None:
    _create_driver(client, license_number="LN-700")

    response = client.post(
        "/api/v1/drivers",
        json={"name": "Someone Else", "license_number": "LN-700", "date_of_birth": "1985-05-05"},
    )
    assert response.status_code >= 400
