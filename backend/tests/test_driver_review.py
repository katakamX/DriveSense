"""Endpoint tests for the staff-side driver-application review queue (M-Auth-4)."""

from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from tests.conftest import register_staff
from tests.test_driver_applications import BASIC_INFO, register_and_login, upload_all_required


async def test_requires_authentication(client: TestClient, db_session: AsyncSession) -> None:
    assert client.get("/api/v1/driver-review/applications").status_code == 401


async def test_plain_user_is_forbidden(client: TestClient, db_session: AsyncSession) -> None:
    register_and_login(client, "review-plainuser@example.com")

    assert client.get("/api/v1/driver-review/applications").status_code == 403


async def test_list_applications_filters_by_status(
    client: TestClient, db_session: AsyncSession, storage_root: Path
) -> None:
    register_and_login(client, "review-applicant-draft@example.com")
    client.post(
        "/api/v1/driver-applications", json={**BASIC_INFO, "license_number": "REV-DRAFT-001"}
    )
    client.post("/api/v1/auth/logout")

    register_and_login(client, "review-applicant-pending@example.com")
    client.post(
        "/api/v1/driver-applications", json={**BASIC_INFO, "license_number": "REV-PEND-001"}
    )
    upload_all_required(client)
    client.post("/api/v1/driver-applications/me/submit")
    client.post("/api/v1/auth/logout")

    await register_staff(client, db_session, "review-staff-filter@example.com")

    response = client.get("/api/v1/driver-review/applications", params={"status": "pending"})

    assert response.status_code == 200, response.text
    body = response.json()
    assert len(body) == 1
    assert body[0]["license_number"] == "REV-PEND-001"
    assert body[0]["documents_uploaded"] == body[0]["documents_required"]


async def test_get_application_returns_full_detail(
    client: TestClient, db_session: AsyncSession, storage_root: Path
) -> None:
    register_and_login(client, "review-applicant-detail@example.com")
    created = client.post(
        "/api/v1/driver-applications", json={**BASIC_INFO, "license_number": "REV-DET-001"}
    ).json()
    client.post("/api/v1/auth/logout")

    await register_staff(client, db_session, "review-staff-detail@example.com")

    response = client.get(f"/api/v1/driver-review/applications/{created['id']}")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["license_number"] == "REV-DET-001"
    assert body["status"] == "draft"
    assert body["documents"] == []


async def test_get_application_not_found(client: TestClient, db_session: AsyncSession) -> None:
    await register_staff(client, db_session, "review-staff-404@example.com")

    response = client.get(
        "/api/v1/driver-review/applications/00000000-0000-0000-0000-000000000000"
    )

    assert response.status_code == 404
