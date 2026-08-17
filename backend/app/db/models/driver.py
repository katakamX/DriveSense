import uuid
from datetime import date, datetime
from enum import StrEnum

from sqlalchemy import Date, DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.models.vehicle import Vehicle


class DriverStatus(StrEnum):
    """Where a driver application sits in review.

    `DRAFT` is the state an application occupies while its 13 documents are
    still being uploaded one request at a time; it becomes `PENDING` only once
    the set is complete and the applicant submits it for review.
    """

    DRAFT = "draft"
    PENDING = "pending"
    VERIFIED = "verified"
    REJECTED = "rejected"


class Driver(Base):
    __tablename__ = "drivers"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(200))
    license_number: Mapped[str] = mapped_column(String(50), unique=True)
    date_of_birth: Mapped[date] = mapped_column(Date)
    # Opaque client-facing code used by the browser-camera monitor socket to
    # identify a session without exposing the UUID primary key. Nullable
    # because existing drivers predate it and backfill is a separate concern.
    driver_code: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True)
    # Which vehicle this driver is currently in, not a history of assignments
    # — nothing in the product needs "which vehicle was driver X in on date Y"
    # yet, and that's a different, bigger model (with its own start/end times)
    # if it ever does.
    current_vehicle_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("vehicles.id"), nullable=True
    )
    current_vehicle: Mapped[Vehicle | None] = relationship()
    # The `User` whose driver application produced this row. Nullable because
    # staff-created drivers (the `/drivers` CRUD endpoints) have no applicant
    # behind them; unique because a user carries at most one application.
    # SET NULL rather than CASCADE: deleting a login should not destroy the
    # driving history attached to the driver.
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), unique=True, nullable=True
    )
    # Plain string, not a DB enum, matching `User.role`'s convention here —
    # validated at the application boundary (`DriverStatus`).
    status: Mapped[str] = mapped_column(String(20), default=DriverStatus.DRAFT)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
