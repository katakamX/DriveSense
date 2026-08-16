import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import Boolean, DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class UserRole(StrEnum):
    """Extensible on purpose: M-Auth-4 adds `employee` as a distinct onboarding
    flow, and more roles are expected. Only what step 6 needs exists so far."""

    USER = "user"
    EMPLOYEE = "employee"
    ADMIN = "admin"


class User(Base):
    """Staff/admin/employee login identity — not the monitored `Driver`."""

    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(320), unique=True)
    # Nullable: a Google-OAuth-only user (M-Auth-2) has no local password.
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Plain string, not a DB enum, matching `Trip.status`'s convention in this
    # codebase — validated at the application boundary (`UserRole`), not by a
    # DB constraint.
    role: Mapped[str] = mapped_column(String(20), default=UserRole.USER)
    email_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    # Hashed (sha256) like a session token, not plaintext - a DB dump
    # shouldn't hand out live OTP codes. Both null once nothing is pending
    # (verified, or never requested).
    otp_code_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    otp_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
