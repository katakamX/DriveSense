import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, String, func
from sqlalchemy.dialects.postgresql import BIGINT
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class DriverState(Base):
    """One aggregated observation from the CV process (ADR 0002).

    Drowsiness, PERCLOS and blink rate are nullable: the CV process reports
    `face_detected=False` (with the rest unset) rather than a fabricated
    neutral value when no face is in frame, matching the same "None over a
    made-up value" discipline `Telemetry` uses for optional PIDs.
    `distraction` is nullable and always unset by this milestone's CV
    process — no gaze/head-pose estimation is implemented yet (cv/README.md).
    """

    __tablename__ = "driver_states"
    __table_args__ = (Index("ix_driver_states_trip_id_recorded_at", "trip_id", "recorded_at"),)

    id: Mapped[int] = mapped_column(BIGINT, primary_key=True, autoincrement=True)
    trip_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("trips.id"))
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ingested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    schema_version: Mapped[str] = mapped_column(String(10))
    face_detected: Mapped[bool] = mapped_column(Boolean)
    calibrated: Mapped[bool] = mapped_column(Boolean)
    drowsiness: Mapped[float | None] = mapped_column(Float, nullable=True)
    distraction: Mapped[float | None] = mapped_column(Float, nullable=True)
    perclos: Mapped[float | None] = mapped_column(Float, nullable=True)
    blink_rate_per_min: Mapped[float | None] = mapped_column(Float, nullable=True)
