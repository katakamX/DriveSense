"""Request/response schemas for telemetry ingestion.

Defined independently of `contracts.TelemetryFrame` (no backend dependency on
the contracts package). `extra="allow"` lets frame fields this schema doesn't
name pass through into storage rather than being rejected, so contract
evolution doesn't require a schema change here to keep accepting frames.
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class TelemetryFrameIn(BaseModel):
    model_config = ConfigDict(extra="allow")

    schema_version: str
    ts: datetime
    speed_kph: float
    accel_ms2: float
    lateral_accel_ms2: float
    lat: float | None = None
    lon: float | None = None


class TelemetryBatchRequest(BaseModel):
    frames: list[TelemetryFrameIn] = Field(min_length=1)


class TelemetryBatchResponse(BaseModel):
    accepted: int
