"""Health endpoint tests.

The readiness tests deliberately stub the database check rather than requiring
a live PostgreSQL instance, so the unit suite stays fast and runnable in CI
without services. Integration coverage against a real database arrives with
Milestone 3.
"""

from fastapi.testclient import TestClient

from app.api.v1 import health


def test_health_reports_ok(client: TestClient) -> None:
    response = client.get("/api/v1/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["version"]
    assert body["service"]


def test_readiness_ok_when_database_reachable(client: TestClient, monkeypatch: object) -> None:
    async def fake_check() -> bool:
        return True

    monkeypatch.setattr(health, "_check_database", fake_check)  # type: ignore[attr-defined]

    response = client.get("/api/v1/health/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ready", "database": True}


def test_readiness_returns_503_when_database_unreachable(
    client: TestClient, monkeypatch: object
) -> None:
    async def fake_check() -> bool:
        return False

    monkeypatch.setattr(health, "_check_database", fake_check)  # type: ignore[attr-defined]

    response = client.get("/api/v1/health/ready")

    assert response.status_code == 503
    assert response.json() == {"status": "not_ready", "database": False}


def test_openapi_schema_is_served(client: TestClient) -> None:
    response = client.get("/openapi.json")

    assert response.status_code == 200
    assert "/api/v1/health" in response.json()["paths"]
