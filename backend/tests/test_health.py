"""Health endpoint tests.

`/health/ready` checks the database via the `get_db` dependency, so the
"unreachable" case is exercised by overriding `get_db` with a session stand-in
that raises on `execute`, the same override pattern conftest.py's `client`
fixture uses for the real DB connection.
"""

from collections.abc import AsyncIterator

from fastapi.testclient import TestClient

from app.db.session import get_db
from app.main import create_app


class _RaisingSession:
    async def execute(self, *args: object, **kwargs: object) -> None:
        raise ConnectionError("database unreachable")


def test_health_reports_ok(client: TestClient) -> None:
    response = client.get("/api/v1/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["version"]
    assert body["service"]


def test_readiness_ok_when_database_reachable(client: TestClient) -> None:
    response = client.get("/api/v1/health/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ready", "database": True}


def test_readiness_returns_503_when_database_unreachable() -> None:
    app = create_app()

    async def override_get_db() -> AsyncIterator[_RaisingSession]:
        yield _RaisingSession()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/api/v1/health/ready")
    app.dependency_overrides.clear()

    assert response.status_code == 503
    assert response.json() == {"status": "not_ready", "database": False}


def test_openapi_schema_is_served(client: TestClient) -> None:
    response = client.get("/openapi.json")

    assert response.status_code == 200
    assert "/api/v1/health" in response.json()["paths"]
