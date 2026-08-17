"""Storage-layer tests for driver-application documents (ADR 0009)."""

import uuid
from pathlib import Path

import pytest

from app.core.documents import (
    DocumentValidationError,
    document_absolute_path,
    save_document,
    validate_upload,
)
from app.db.models import DocumentType

PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
PDF_BYTES = b"%PDF-1.7\n" + b"\x00" * 64


def test_save_document_writes_under_driver_directory(storage_root: Path) -> None:
    driver_id = uuid.uuid4()

    stored = save_document(driver_id, DocumentType.EXTERIOR_PHOTO, "image/png", PNG_BYTES)

    assert stored.file_path.startswith(f"{driver_id}/exterior_photo_")
    assert stored.file_path.endswith(".png")
    assert stored.size_bytes == len(PNG_BYTES)
    assert stored.content_type == "image/png"

    written = storage_root / stored.file_path
    assert written.read_bytes() == PNG_BYTES


def test_save_document_generates_a_distinct_name_per_upload(storage_root: Path) -> None:
    """Five exterior photos must coexist, so names cannot derive from the type alone."""
    driver_id = uuid.uuid4()

    paths = {
        save_document(driver_id, DocumentType.EXTERIOR_PHOTO, "image/png", PNG_BYTES).file_path
        for _ in range(5)
    }

    assert len(paths) == 5
    assert len(list((storage_root / str(driver_id)).iterdir())) == 5


def test_save_document_accepts_pdf(storage_root: Path) -> None:
    stored = save_document(uuid.uuid4(), DocumentType.AADHAR, "application/pdf", PDF_BYTES)

    assert stored.file_path.endswith(".pdf")
    assert (storage_root / stored.file_path).exists()


def test_rejects_disallowed_content_type() -> None:
    with pytest.raises(DocumentValidationError, match="Unsupported file type"):
        validate_upload("image/jpeg", b"\xff\xd8\xff\xe0")


def test_rejects_content_that_does_not_match_declared_type() -> None:
    """A declared `Content-Type` is client-controlled; the bytes decide."""
    with pytest.raises(DocumentValidationError, match="does not match"):
        validate_upload("image/png", PDF_BYTES)


def test_rejects_empty_file() -> None:
    with pytest.raises(DocumentValidationError, match="empty"):
        validate_upload("image/png", b"")


def test_rejects_oversized_file(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.config import get_settings

    monkeypatch.setenv("DOCUMENT_MAX_BYTES", "128")
    get_settings.cache_clear()
    try:
        with pytest.raises(DocumentValidationError, match="limit"):
            validate_upload("image/png", b"\x89PNG\r\n\x1a\n" + b"\x00" * 512)
    finally:
        get_settings.cache_clear()


def test_upload_filename_cannot_escape_the_storage_root(storage_root: Path) -> None:
    """The client's filename is discarded, so a traversal attempt is inert."""
    driver_id = uuid.uuid4()

    stored = save_document(driver_id, DocumentType.FACE_PHOTO, "image/png", PNG_BYTES)

    absolute = (storage_root / stored.file_path).resolve()
    assert absolute.is_relative_to(storage_root.resolve())
    assert ".." not in stored.file_path


def test_document_absolute_path_refuses_traversal(storage_root: Path) -> None:
    with pytest.raises(DocumentValidationError, match="Invalid document path"):
        document_absolute_path("../../etc/passwd")


def test_document_absolute_path_resolves_a_stored_file(storage_root: Path) -> None:
    stored = save_document(uuid.uuid4(), DocumentType.INSURANCE, "application/pdf", PDF_BYTES)

    assert document_absolute_path(stored.file_path).read_bytes() == PDF_BYTES
