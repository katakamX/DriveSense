"""Endpoint tests for the staff-side driver-application review queue (M-Auth-4)."""

from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from tests.conftest import register_staff
from tests.test_driver_applications import (
    BASIC_INFO,
    register_and_login,
    upload,
    upload_all_required,
)


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


async def _submitted_application(
    client: TestClient, license_number: str, applicant_email: str
) -> dict:
    register_and_login(client, applicant_email)
    client.post(
        "/api/v1/driver-applications", json={**BASIC_INFO, "license_number": license_number}
    )
    upload_all_required(client)
    submitted = client.post("/api/v1/driver-applications/me/submit").json()
    client.post("/api/v1/auth/logout")
    return submitted


async def test_verify_moves_pending_to_verified(
    client: TestClient, db_session: AsyncSession, storage_root: Path
) -> None:
    application = await _submitted_application(
        client, "REV-VERIFY-001", "review-applicant-verify@example.com"
    )
    await register_staff(client, db_session, "review-staff-verify@example.com")

    response = client.post(f"/api/v1/driver-review/applications/{application['id']}/verify")

    assert response.status_code == 200, response.text
    assert response.json()["status"] == "verified"


async def test_reject_moves_pending_to_rejected(
    client: TestClient, db_session: AsyncSession, storage_root: Path
) -> None:
    application = await _submitted_application(
        client, "REV-REJECT-001", "review-applicant-reject@example.com"
    )
    await register_staff(client, db_session, "review-staff-reject@example.com")

    response = client.post(f"/api/v1/driver-review/applications/{application['id']}/reject")

    assert response.status_code == 200, response.text
    assert response.json()["status"] == "rejected"


async def test_verify_non_pending_application_conflicts(
    client: TestClient, db_session: AsyncSession, storage_root: Path
) -> None:
    register_and_login(client, "review-applicant-draftonly@example.com")
    created = client.post(
        "/api/v1/driver-applications", json={**BASIC_INFO, "license_number": "REV-DRAFTONLY-001"}
    ).json()
    client.post("/api/v1/auth/logout")
    await register_staff(client, db_session, "review-staff-draftonly@example.com")

    response = client.post(f"/api/v1/driver-review/applications/{created['id']}/verify")

    assert response.status_code == 409


async def test_rejected_application_is_editable_again(
    client: TestClient, db_session: AsyncSession, storage_root: Path
) -> None:
    application = await _submitted_application(
        client, "REV-REEDIT-001", "review-applicant-reedit@example.com"
    )
    await register_staff(client, db_session, "review-staff-reedit@example.com")
    client.post(f"/api/v1/driver-review/applications/{application['id']}/reject")
    client.post("/api/v1/auth/logout")

    client.post(
        "/api/v1/auth/login",
        json={"email": "review-applicant-reedit@example.com", "password": "correcthorsebattery"},
    )
    face_photo_id = next(
        doc["id"] for doc in application["documents"] if doc["document_type"] == "face_photo"
    )
    client.delete(f"/api/v1/driver-applications/me/documents/{face_photo_id}")

    response = upload(client, "face_photo")

    assert response.status_code == 201, response.text
    assert response.json()["status"] == "rejected"


async def test_get_document_file_returns_the_bytes(
    client: TestClient, db_session: AsyncSession, storage_root: Path
) -> None:
    register_and_login(client, "review-applicant-file@example.com")
    client.post(
        "/api/v1/driver-applications", json={**BASIC_INFO, "license_number": "REV-FILE-001"}
    )
    uploaded = upload(client, "face_photo").json()
    driver_id = uploaded["id"]
    document_id = uploaded["documents"][0]["id"]
    client.post("/api/v1/auth/logout")

    await register_staff(client, db_session, "review-staff-file@example.com")

    response = client.get(
        f"/api/v1/driver-review/applications/{driver_id}/documents/{document_id}/file"
    )

    assert response.status_code == 200
    assert response.content.startswith(b"\x89PNG")
    assert response.headers["content-type"] == "image/png"


async def test_get_document_file_requires_staff(
    client: TestClient, db_session: AsyncSession, storage_root: Path
) -> None:
    register_and_login(client, "review-applicant-file-noauth@example.com")
    uploaded = client.post(
        "/api/v1/driver-applications", json={**BASIC_INFO, "license_number": "REV-FILE-NOAUTH-001"}
    ).json()
    driver_id = uploaded["id"]
    document_id = upload(client, "face_photo").json()["documents"][0]["id"]

    # Still logged in as the plain applicant: staff role required, not just a session.
    own_document_response = client.get(
        f"/api/v1/driver-review/applications/{driver_id}/documents/{document_id}/file"
    )
    assert own_document_response.status_code == 403

    client.post("/api/v1/auth/logout")
    anonymous_response = client.get(
        f"/api/v1/driver-review/applications/{driver_id}/documents/{document_id}/file"
    )
    assert anonymous_response.status_code == 401


async def test_get_document_file_wrong_driver_404s(
    client: TestClient, db_session: AsyncSession, storage_root: Path
) -> None:
    register_and_login(client, "review-applicant-file-a@example.com")
    client.post(
        "/api/v1/driver-applications", json={**BASIC_INFO, "license_number": "REV-FILE-A-001"}
    )
    document_id = upload(client, "face_photo").json()["documents"][0]["id"]
    client.post("/api/v1/auth/logout")

    register_and_login(client, "review-applicant-file-b@example.com")
    other = client.post(
        "/api/v1/driver-applications", json={**BASIC_INFO, "license_number": "REV-FILE-B-001"}
    ).json()
    client.post("/api/v1/auth/logout")

    await register_staff(client, db_session, "review-staff-file-mismatch@example.com")

    response = client.get(
        f"/api/v1/driver-review/applications/{other['id']}/documents/{document_id}/file"
    )

    assert response.status_code == 404
