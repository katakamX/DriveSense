"""Read-only schemas for a single trip's detail sub-resources (M12 page 2).

Mirror the persisted `RiskWindow`/`DrivingEvent`/`Telemetry` rows directly
(unlike `RiskOut` in `schemas/risk.py`, which shapes the live-stream
`RiskAssessment` dataclass) — these are DB reads, not stream payloads.
"""

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class RiskWindowRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    window_start: datetime
    window_end: datetime
    sample_count: int
    coverage_ratio: float

    score: float
    band: str
    confidence: float
    provenance: str
    model_available: bool
    gated: bool

    rule_band: str
    matched_rules: list[str]
    model_band: str | None
    model_score: float | None
    model_predicted_class: str | None
    probabilities: dict[str, float] | None
    contributions: list[dict[str, Any]] | None
    contributions_remainder: float | None

    risk_engine_version: str
    feature_version: str
    rubric_version: str
    model_version: str | None


class DrivingEventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    trip_id: uuid.UUID
    event_type: str
    occurred_at: datetime
    measured_value: float
    threshold_value: float


class TelemetryPointRead(BaseModel):
    """Route/speed points only — `raw_frame` stays internal, it's an ingest
    artefact, not something a detail page has a use for."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    recorded_at: datetime
    speed_kph: float
    accel_ms2: float
    lateral_accel_ms2: float
    lat: float | None
    lon: float | None
