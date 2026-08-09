from fastapi.testclient import TestClient


def _create_vehicle(client: TestClient, **overrides: object) -> dict:
    payload = {
        "make": "Toyota",
        "model": "Corolla",
        "year": 2022,
        "vin": "1HGCM82633A004352",
        "license_plate": "ABC-123",
    }
    payload.update(overrides)
    response = client.post("/api/v1/vehicles", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def test_create_vehicle(client: TestClient) -> None:
    body = _create_vehicle(client)
    assert body["make"] == "Toyota"
    assert body["vin"] == "1HGCM82633A004352"
    assert "id" in body


def test_list_vehicles(client: TestClient) -> None:
    _create_vehicle(client, vin="VIN0000000000001", license_plate="P-001")
    _create_vehicle(client, vin="VIN0000000000002", license_plate="P-002")

    response = client.get("/api/v1/vehicles")
    assert response.status_code == 200
    assert len(response.json()) >= 2


def test_list_vehicles_pagination(client: TestClient) -> None:
    for i in range(3):
        _create_vehicle(client, vin=f"VIN000000000010{i}", license_plate=f"P-10{i}")

    response = client.get("/api/v1/vehicles", params={"limit": 1, "offset": 0})
    assert response.status_code == 200
    assert len(response.json()) == 1


def test_list_vehicles_filter_by_make(client: TestClient) -> None:
    _create_vehicle(client, make="Honda", vin="VIN0000000000020", license_plate="P-200")
    _create_vehicle(client, make="Toyota", vin="VIN0000000000021", license_plate="P-201")

    response = client.get("/api/v1/vehicles", params={"make": "Honda"})
    assert response.status_code == 200
    body = response.json()
    assert all(v["make"] == "Honda" for v in body)
    assert len(body) == 1


def test_get_vehicle_by_id(client: TestClient) -> None:
    created = _create_vehicle(client, vin="VIN0000000000030", license_plate="P-300")

    response = client.get(f"/api/v1/vehicles/{created['id']}")
    assert response.status_code == 200
    assert response.json()["id"] == created["id"]


def test_get_vehicle_not_found(client: TestClient) -> None:
    response = client.get("/api/v1/vehicles/00000000-0000-0000-0000-000000000000")
    assert response.status_code == 404


def test_update_vehicle(client: TestClient) -> None:
    created = _create_vehicle(client, vin="VIN0000000000040", license_plate="P-400")

    response = client.patch(f"/api/v1/vehicles/{created['id']}", json={"model": "Camry"})
    assert response.status_code == 200
    assert response.json()["model"] == "Camry"


def test_update_vehicle_not_found(client: TestClient) -> None:
    response = client.patch(
        "/api/v1/vehicles/00000000-0000-0000-0000-000000000000", json={"model": "X"}
    )
    assert response.status_code == 404


def test_delete_vehicle(client: TestClient) -> None:
    created = _create_vehicle(client, vin="VIN0000000000050", license_plate="P-500")

    response = client.delete(f"/api/v1/vehicles/{created['id']}")
    assert response.status_code == 204

    response = client.get(f"/api/v1/vehicles/{created['id']}")
    assert response.status_code == 404


def test_delete_vehicle_not_found(client: TestClient) -> None:
    response = client.delete("/api/v1/vehicles/00000000-0000-0000-0000-000000000000")
    assert response.status_code == 404


def test_create_vehicle_duplicate_vin_conflicts(client: TestClient) -> None:
    _create_vehicle(client, vin="VIN0000000000060", license_plate="P-600")

    response = client.post(
        "/api/v1/vehicles",
        json={
            "make": "Honda",
            "model": "Civic",
            "year": 2020,
            "vin": "VIN0000000000060",
            "license_plate": "P-601",
        },
    )
    assert response.status_code >= 400
