"""One persisted risk assessment: a window, its band, and why.

The versions are stored per row rather than only per trip, and that is the
whole point of `RISK_ENGINE_VERSION` existing. Without them, a trip re-scored
under a later engine is indistinguishable from a trip driven differently, and
the first question anyone asks of a historical risk number — "was this
produced by the code we run today?" — becomes unanswerable.
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Index, Integer, Numeric, String
from sqlalchemy import func as sa_func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class RiskWindow(Base):
    __tablename__ = "risk_windows"
    __table_args__ = (Index("ix_risk_windows_trip_id_window_end", "trip_id", "window_end"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    trip_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("trips.id"))

    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    window_end: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    sample_count: Mapped[int] = mapped_column(Integer)
    coverage_ratio: Mapped[float] = mapped_column(Numeric(4, 3))

    score: Mapped[float] = mapped_column(Numeric(5, 2))
    band: Mapped[str] = mapped_column(String(20))
    confidence: Mapped[float] = mapped_column(Numeric(4, 3))
    provenance: Mapped[str] = mapped_column(String(30))
    model_available: Mapped[bool] = mapped_column(Boolean)
    gated: Mapped[bool] = mapped_column(Boolean)

    rule_band: Mapped[str] = mapped_column(String(20))
    matched_rules: Mapped[list[str]] = mapped_column(JSONB)
    model_band: Mapped[str | None] = mapped_column(String(20), nullable=True)
    model_score: Mapped[float | None] = mapped_column(Numeric(5, 2), nullable=True)
    model_predicted_class: Mapped[str | None] = mapped_column(String(20), nullable=True)
    probabilities: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    # Top-k contributions plus the summed tail, so the stored explanation
    # still reconciles against the model's centered logit after truncation.
    contributions: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB, nullable=True)
    contributions_remainder: Mapped[float | None] = mapped_column(Numeric(12, 8), nullable=True)

    risk_engine_version: Mapped[str] = mapped_column(String(20))
    feature_version: Mapped[str] = mapped_column(String(20))
    rubric_version: Mapped[str] = mapped_column(String(20))
    model_version: Mapped[str | None] = mapped_column(String(64), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=sa_func.now()
    )
