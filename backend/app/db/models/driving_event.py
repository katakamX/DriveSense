import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Index, String, func
from sqlalchemy.dialects.postgresql import BIGINT
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class DrivingEvent(Base):
    __tablename__ = "driving_events"
    __table_args__ = (Index("ix_driving_events_trip_id_occurred_at", "trip_id", "occurred_at"),)

    id: Mapped[int] = mapped_column(BIGINT, primary_key=True, autoincrement=True)
    trip_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("trips.id"))
    telemetry_id: Mapped[int] = mapped_column(BIGINT, ForeignKey("telemetry.id"))
    event_type: Mapped[str] = mapped_column(String(30))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    measured_value: Mapped[float] = mapped_column(Float)
    threshold_value: Mapped[float] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
