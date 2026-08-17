import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class DocumentType(StrEnum):
    """The document kinds a driver application must supply.

    Photos of the vehicle and the applicant's face are collected in the app;
    the last three are government/ownership paperwork uploaded as scans.
    """

    EXTERIOR_PHOTO = "exterior_photo"
    INTERIOR_PHOTO = "interior_photo"
    PLATE_PHOTO = "plate_photo"
    FACE_PHOTO = "face_photo"
    AADHAR = "aadhar"
    INSURANCE = "insurance"
    VEHICLE_REGISTRATION = "vehicle_registration"


# How many files of each type a complete application carries — 13 in total.
# Lives next to the enum rather than in the endpoint because both the storage
# layer and the submit check need it, and it is a property of the document
# taxonomy itself, not of any one caller.
REQUIRED_DOCUMENT_COUNTS: dict[DocumentType, int] = {
    DocumentType.EXTERIOR_PHOTO: 5,
    DocumentType.INTERIOR_PHOTO: 2,
    DocumentType.PLATE_PHOTO: 2,
    DocumentType.FACE_PHOTO: 1,
    DocumentType.AADHAR: 1,
    DocumentType.INSURANCE: 1,
    DocumentType.VEHICLE_REGISTRATION: 1,
}

REQUIRED_DOCUMENT_TOTAL = sum(REQUIRED_DOCUMENT_COUNTS.values())


class DocumentUpload(Base):
    """One uploaded file belonging to a driver's application.

    Rows are append-only per upload; a type can legitimately appear several
    times (five exterior photos), so there is no unique constraint on
    (driver_id, document_type) — completeness is checked by counting against
    `REQUIRED_DOCUMENT_COUNTS` at submit time.
    """

    __tablename__ = "document_uploads"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    # Documents have no meaning without the application they belong to.
    driver_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("drivers.id", ondelete="CASCADE"), index=True
    )
    # Plain string, not a DB enum, matching `User.role`/`Trip.status` here —
    # validated at the application boundary (`DocumentType`).
    document_type: Mapped[str] = mapped_column(String(40))
    # Path relative to the configured storage root, so the root can move
    # (container volume, later an object-store prefix) without rewriting rows.
    file_path: Mapped[str] = mapped_column(String(500))
    content_type: Mapped[str] = mapped_column(String(100))
    size_bytes: Mapped[int] = mapped_column(Integer)
    uploaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
