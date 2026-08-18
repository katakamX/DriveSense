"""Request/response schemas for the driver-application flow (M-Auth-3)."""

import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict


class DriverApplicationCreate(BaseModel):
    """The basic-info step, submitted before any document is uploaded."""

    name: str
    license_number: str
    date_of_birth: date


class DocumentUploadRead(BaseModel):
    """A stored document, as the applicant's own UI sees it.

    `file_path` is deliberately absent: it is a server-side storage detail
    (ADR 0009), and the client addresses a document by `id`.
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    document_type: str
    content_type: str
    size_bytes: int
    uploaded_at: datetime


class DocumentRequirementRead(BaseModel):
    """One row of the "3 of 5 exterior photos" progress the form renders."""

    document_type: str
    required: int
    uploaded: int


class DriverApplicationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    license_number: str
    date_of_birth: date
    status: str
    created_at: datetime
    documents: list[DocumentUploadRead]
    requirements: list[DocumentRequirementRead]
    # Whether every requirement is met — the condition `POST /submit` enforces.
    # Computed server-side so the client never has to reimplement the rule to
    # decide whether to enable its submit button.
    is_complete: bool


class DriverApplicationSummary(BaseModel):
    """One row of the staff review queue (M-Auth-4).

    Deliberately lighter than `DriverApplicationRead`: the queue lists many
    applications at once, and a reviewer needs the status/progress to decide
    which to open, not every document row up front.
    """

    id: uuid.UUID
    name: str
    license_number: str
    status: str
    created_at: datetime
    documents_uploaded: int
    documents_required: int
