from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import UserRole
from tests.conftest import register_staff


def test_system_health_requires_authentication(client: TestClient) -> None:
    assert client.get("/api/v1/admin/system-health").status_code == 401


async def test_system_health_refuses_non_admin(
    client: TestClient, db_session: AsyncSession
) -> None:
    await register_staff(client, db_session, "admin-employee@example.com", role=UserRole.EMPLOYEE)
    response = client.get("/api/v1/admin/system-health")
    assert response.status_code == 403


async def test_system_health_as_admin(client: TestClient, db_session: AsyncSession) -> None:
    await register_staff(client, db_session, "admin-health@example.com")
    response = client.get("/api/v1/admin/system-health")
    assert response.status_code == 200
    body = response.json()
    assert body["risk_engine_version"] == "1"
    assert "model_version" in body
    assert "model_loaded" in body
