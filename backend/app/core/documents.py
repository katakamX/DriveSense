"""Local-disk storage for driver-application documents (see ADR 0009).

Files land under `settings.document_storage_dir` as::

    {driver_id}/{document_type}_{uuid4}.{ext}

Nothing the client sends is used to build that path — the driver id is a UUID
the caller never chooses, the document type is validated against
`DocumentType`, and the basename is generated here. The uploaded filename is
discarded entirely, which is what makes traversal (`../../etc/passwd`),
absolute paths, NTFS alternate data streams and Windows device names
(`CON`, `NUL`) non-issues rather than things to sanitise. `_resolve_under_root`
then re-checks the result on the way out, so a future caller that does thread
a client-supplied segment in here fails loudly instead of writing outside the
root.
"""

import uuid
from dataclasses import dataclass
from pathlib import Path

from app.config import get_settings
from app.db.models import DocumentType

# Declared content type -> on-disk extension. PNG and PDF only: photos come
# from the app's own capture flow, and paperwork is scanned. Accepting JPEG or
# HEIC as well is a product decision, not a technical obstacle.
ALLOWED_CONTENT_TYPES: dict[str, str] = {
    "image/png": "png",
    "application/pdf": "pdf",
}

# Leading bytes each accepted format must actually start with. The multipart
# `Content-Type` header is client-controlled and therefore not evidence of
# anything; this is the check that decides what the file really is.
_MAGIC_PREFIXES: dict[str, bytes] = {
    "image/png": b"\x89PNG\r\n\x1a\n",
    "application/pdf": b"%PDF-",
}


class DocumentValidationError(ValueError):
    """An upload that must be rejected — wrong type, empty, or too large.

    Carries no path or filesystem detail: the endpoint turns `str(exc)` into a
    client-facing message.
    """


@dataclass(frozen=True)
class StoredDocument:
    """Where a saved upload landed, in the form `DocumentUpload` records it."""

    file_path: str
    content_type: str
    size_bytes: int


def _resolve_under_root(relative_path: str, root: Path) -> Path:
    """Resolve `relative_path` against `root`, refusing anything that escapes it."""
    candidate = (root / relative_path).resolve()
    if not candidate.is_relative_to(root.resolve()):
        raise DocumentValidationError("Invalid document path")
    return candidate


def validate_upload(content_type: str | None, data: bytes) -> str:
    """Check an upload's declared type, magic bytes and size; return its extension.

    Raises `DocumentValidationError` on anything unacceptable.
    """
    settings = get_settings()

    if content_type is None or content_type not in ALLOWED_CONTENT_TYPES:
        allowed = ", ".join(sorted(ALLOWED_CONTENT_TYPES))
        raise DocumentValidationError(f"Unsupported file type; allowed types are {allowed}")
    if not data:
        raise DocumentValidationError("File is empty")
    if len(data) > settings.document_max_bytes:
        limit_mb = settings.document_max_bytes / (1024 * 1024)
        raise DocumentValidationError(f"File exceeds the {limit_mb:.0f} MB limit")
    if not data.startswith(_MAGIC_PREFIXES[content_type]):
        raise DocumentValidationError(
            f"File content does not match its declared type {content_type}"
        )

    return ALLOWED_CONTENT_TYPES[content_type]


def save_document(
    driver_id: uuid.UUID, document_type: DocumentType, content_type: str | None, data: bytes
) -> StoredDocument:
    """Validate an upload and write it under the driver's directory.

    The returned `file_path` is relative to the storage root, matching what
    `DocumentUpload.file_path` stores.
    """
    extension = validate_upload(content_type, data)
    root = get_settings().document_storage_dir

    relative_path = f"{driver_id}/{document_type.value}_{uuid.uuid4().hex}.{extension}"
    destination = _resolve_under_root(relative_path, root)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(data)

    # `content_type` is not None here: `validate_upload` rejects that case.
    assert content_type is not None
    return StoredDocument(file_path=relative_path, content_type=content_type, size_bytes=len(data))


def document_absolute_path(file_path: str) -> Path:
    """Absolute path of a stored document, for serving or deleting it later."""
    return _resolve_under_root(file_path, get_settings().document_storage_dir)
