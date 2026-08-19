import uuid

from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import User, UserRole
from tests.conftest import register_staff


async def _create_target(db_session: AsyncSession, email: str) -> str:
    """Insert a target user directly, bypassing `/auth/register` — registering
    through `client` would overwrite the calling test's admin session cookie
    with the new user's, since register logs the caller in.
    """
    user = User(id=uuid.uuid4(), email=email, role=UserRole.USER, email_verified=True)
    db_session.add(user)
    await db_session.commit()
    return str(user.id)


async def test_list_users_requires_admin(client: TestClient, db_session: AsyncSession) -> None:
    assert client.get("/api/v1/users").status_code == 401

    await register_staff(client, db_session, "users-employee@example.com", role=UserRole.EMPLOYEE)
    response = client.get("/api/v1/users")
    assert response.status_code == 403


async def test_list_users_as_admin(client: TestClient, db_session: AsyncSession) -> None:
    await register_staff(client, db_session, "users-admin@example.com")
    response = client.get("/api/v1/users")
    assert response.status_code == 200
    body = response.json()
    assert any(u["email"] == "users-admin@example.com" for u in body)


async def test_update_user_role(client: TestClient, db_session: AsyncSession) -> None:
    await register_staff(client, db_session, "users-admin-2@example.com")
    target_id = await _create_target(db_session, "users-target@example.com")

    response = client.patch(f"/api/v1/users/{target_id}/role", json={"role": "employee"})
    assert response.status_code == 200
    assert response.json()["role"] == "employee"


async def test_update_user_role_refuses_non_admin(
    client: TestClient, db_session: AsyncSession
) -> None:
    target_id = await _create_target(db_session, "users-target-2@example.com")

    await register_staff(client, db_session, "users-employee-2@example.com", role=UserRole.EMPLOYEE)
    response = client.patch(f"/api/v1/users/{target_id}/role", json={"role": "admin"})
    assert response.status_code == 403


async def test_update_user_role_not_found(client: TestClient, db_session: AsyncSession) -> None:
    await register_staff(client, db_session, "users-admin-4@example.com")
    response = client.patch(
        "/api/v1/users/00000000-0000-0000-0000-000000000000/role", json={"role": "admin"}
    )
    assert response.status_code == 404


async def test_update_user_role_rejects_invalid_role(
    client: TestClient, db_session: AsyncSession
) -> None:
    await register_staff(client, db_session, "users-admin-3@example.com")
    target_id = await _create_target(db_session, "users-target-3@example.com")

    response = client.patch(f"/api/v1/users/{target_id}/role", json={"role": "superuser"})
    assert response.status_code == 422
