import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Trip(Base):
    __tablename__ = "trips"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    driver_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("drivers.id"))
    vehicle_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("vehicles.id"))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    distance_km: Mapped[float | None] = mapped_column(Numeric(8, 3), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="in_progress")
    speed_limit_kph: Mapped[float | None] = mapped_column(Numeric(6, 2), nullable=True)

    # Written once, when the trip ends, by the risk sink's final flush. All
    # three are nullable because an in-progress trip has no final score, and
    # because a trip scored under engine v1 must stay readable after v2 ships
    # — `risk_engine_version` is what makes "a different engine produced this"
    # answerable rather than a guess.
    risk_score: Mapped[float | None] = mapped_column(Numeric(5, 2), nullable=True)
    risk_band: Mapped[str | None] = mapped_column(String(20), nullable=True)
    risk_engine_version: Mapped[str | None] = mapped_column(String(20), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
