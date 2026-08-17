"""Endpoint tests for the driver-application flow (M-Auth-3)."""

from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import REQUIRED_DOCUMENT_COUNTS, REQUIRED_DOCUMENT_TOTAL

PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
PDF_BYTES = b"%PDF-1.7\n" + b"\x00" * 64

BASIC_INFO = {
    "name": "Asha Rao",
    "license_number": "KA0120249999",
    "date_of_birth": "1996-04-11",
}


def register_and_login(client: TestClient, email: str) -> None:
    """A plain `user`-role login — the role a self-serve applicant actually has."""
    response = client.post(
        "/api/v1/auth/register", json={"email": email, "password": "correcthorsebattery"}
    )
    assert response.status_code == 201, response.text


def upload(client: TestClient, document_type: str, data: bytes = PNG_BYTES) -> object:
    content_type = "application/pdf" if data.startswith(b"%PDF-") else "image/png"
    suffix = "pdf" if content_type == "application/pdf" else "png"
    return client.post(
        "/api/v1/driver-applications/me/documents",
        data={"document_type": document_type},
        files={"file": (f"upload.{suffix}", data, content_type)},
    )


def upload_all_required(client: TestClient) -> None:
    for document_type, count in REQUIRED_DOCUMENT_COUNTS.items():
        data = (
            PDF_BYTES
            if document_type.value in {"aadhar", "insurance", "vehicle_registration"}
            else PNG_BYTES
        )
        for _ in range(count):
            response = upload(client, document_type.value, data)
            assert response.status_code == 201, response.text


async def test_requires_authentication(client: TestClient, db_session: AsyncSession) -> None:
    assert client.post("/api/v1/driver-applications", json=BASIC_INFO).status_code == 401
    assert client.get("/api/v1/driver-applications/me").status_code == 401


async def test_create_application_starts_as_draft(
    client: TestClient, db_session: AsyncSession
) -> None:
    register_and_login(client, "applicant-draft@example.com")

    response = client.post("/api/v1/driver-applications", json=BASIC_INFO)

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["status"] == "draft"
    assert body["is_complete"] is False
    assert body["documents"] == []
    assert sum(row["required"] for row in body["requirements"]) == REQUIRED_DOCUMENT_TOTAL


async def test_second_application_for_same_user_conflicts(
    client: TestClient, db_session: AsyncSession
) -> None:
    register_and_login(client, "applicant-dupe@example.com")
    assert client.post("/api/v1/driver-applications", json=BASIC_INFO).status_code == 201

    second = client.post(
        "/api/v1/driver-applications", json={**BASIC_INFO, "license_number": "KA0120240000"}
    )

    assert second.status_code == 409


async def test_upload_returns_refreshed_progress(
    client: TestClient, db_session: AsyncSession, storage_root: Path
) -> None:
    register_and_login(client, "applicant-progress@example.com")
    client.post("/api/v1/driver-applications", json=BASIC_INFO)

    response = upload(client, "exterior_photo")

    assert response.status_code == 201, response.text
    body = response.json()
    exterior = next(r for r in body["requirements"] if r["document_type"] == "exterior_photo")
    assert exterior == {"document_type": "exterior_photo", "required": 5, "uploaded": 1}
    assert len(body["documents"]) == 1
    assert body["is_complete"] is False
    # `file_path` is a server-side storage detail and must not be exposed.
    assert "file_path" not in body["documents"][0]


async def test_upload_rejects_disallowed_file_type(
    client: TestClient, db_session: AsyncSession, storage_root: Path
) -> None:
    register_and_login(client, "applicant-badtype@example.com")
    client.post("/api/v1/driver-applications", json=BASIC_INFO)

    response = client.post(
        "/api/v1/driver-applications/me/documents",
        data={"document_type": "exterior_photo"},
        files={"file": ("photo.jpg", b"\xff\xd8\xff\xe0hello", "image/jpeg")},
    )

    assert response.status_code == 400
    assert "Unsupported file type" in response.json()["detail"]


async def test_upload_rejects_content_that_lies_about_its_type(
    client: TestClient, db_session: AsyncSession, storage_root: Path
) -> None:
    register_and_login(client, "applicant-liar@example.com")
    client.post("/api/v1/driver-applications", json=BASIC_INFO)

    response = client.post(
        "/api/v1/driver-applications/me/documents",
        data={"document_type": "exterior_photo"},
        files={"file": ("evil.png", b"MZ\x90\x00 not a png", "image/png")},
    )

    assert response.status_code == 400
    assert "does not match" in response.json()["detail"]


async def test_upload_rejects_unknown_document_type(
    client: TestClient, db_session: AsyncSession, storage_root: Path
) -> None:
    register_and_login(client, "applicant-unknowntype@example.com")
    client.post("/api/v1/driver-applications", json=BASIC_INFO)

    response = upload(client, "passport")

    assert response.status_code == 422


async def test_upload_beyond_required_count_conflicts(
    client: TestClient, db_session: AsyncSession, storage_root: Path
) -> None:
    register_and_login(client, "applicant-toomany@example.com")
    client.post("/api/v1/driver-applications", json=BASIC_INFO)
    # face_photo requires exactly one, so the second is one too many.
    assert upload(client, "face_photo").status_code == 201

    response = upload(client, "face_photo")

    assert response.status_code == 409
    assert "already uploaded" in response.json()["detail"]


async def test_delete_document_frees_the_slot(
    client: TestClient, db_session: AsyncSession, storage_root: Path
) -> None:
    register_and_login(client, "applicant-delete@example.com")
    client.post("/api/v1/driver-applications", json=BASIC_INFO)
    created = upload(client, "face_photo").json()
    document_id = created["documents"][0]["id"]

    response = client.delete(f"/api/v1/driver-applications/me/documents/{document_id}")

    assert response.status_code == 200, response.text
    assert response.json()["documents"] == []
    assert upload(client, "face_photo").status_code == 201


async def test_cannot_delete_another_applicants_document(
    client: TestClient, db_session: AsyncSession, storage_root: Path
) -> None:
    register_and_login(client, "applicant-owner@example.com")
    client.post("/api/v1/driver-applications", json=BASIC_INFO)
    document_id = upload(client, "face_photo").json()["documents"][0]["id"]
    client.post("/api/v1/auth/logout")

    register_and_login(client, "applicant-intruder@example.com")
    client.post(
        "/api/v1/driver-applications", json={**BASIC_INFO, "license_number": "KA0120241111"}
    )
    response = client.delete(f"/api/v1/driver-applications/me/documents/{document_id}")

    assert response.status_code == 404


async def test_submit_incomplete_application_is_rejected(
    client: TestClient, db_session: AsyncSession, storage_root: Path
) -> None:
    register_and_login(client, "applicant-incomplete@example.com")
    client.post("/api/v1/driver-applications", json=BASIC_INFO)
    upload(client, "exterior_photo")

    response = client.post("/api/v1/driver-applications/me/submit")

    assert response.status_code == 400
    detail = response.json()["detail"]
    assert "Missing required documents" in detail
    assert "exterior_photo (1/5)" in detail
    assert "aadhar (0/1)" in detail


async def test_complete_application_submits_and_freezes(
    client: TestClient, db_session: AsyncSession, storage_root: Path
) -> None:
    register_and_login(client, "applicant-complete@example.com")
    client.post("/api/v1/driver-applications", json=BASIC_INFO)
    upload_all_required(client)

    response = client.post("/api/v1/driver-applications/me/submit")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "pending"
    assert body["is_complete"] is True
    assert len(body["documents"]) == REQUIRED_DOCUMENT_TOTAL

    # Pending means a reviewer is looking at exactly these files.
    assert client.post("/api/v1/driver-applications/me/submit").status_code == 409
    document_id = body["documents"][0]["id"]
    assert (
        client.delete(f"/api/v1/driver-applications/me/documents/{document_id}").status_code == 409
    )


async def test_get_me_404s_before_an_application_exists(
    client: TestClient, db_session: AsyncSession
) -> None:
    register_and_login(client, "applicant-none@example.com")

    assert client.get("/api/v1/driver-applications/me").status_code == 404
