"""Request/response schema for driver-state ingestion.

Defined independently of `cv.contracts.DriverStateFrame` — same reasoning as
`telemetry.py`: no backend dependency on the CV process's package. There is
no OpenAPI-schema generation step tying the two together (Milestone 3 did not
build it — see ADR 0002's "Negative" section), so this schema and
`cv/contracts.py` are two hand-maintained copies that must be kept in sync by
hand. `extra="allow"` matches `TelemetryFrameIn`'s reasoning: a field this
schema doesn't name still passes through rather than being rejected.
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class DriverStateIn(BaseModel):
    model_config = ConfigDict(extra="allow")

    schema_version: str
    trip_id: str
    ts: datetime
    face_detected: bool
    calibrated: bool = False
    drowsiness: float | None = Field(default=None, ge=0.0, le=1.0)
    distraction: float | None = Field(default=None, ge=0.0, le=1.0)
    perclos: float | None = Field(default=None, ge=0.0, le=1.0)
    blink_rate_per_min: float | None = Field(default=None, ge=0.0)


class DriverStateResponse(BaseModel):
    accepted: bool
