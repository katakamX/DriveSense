"""The `DriverStateFrame` contract (ADR 0002).

This is a hand-maintained copy of `backend/app/schemas/driver_state.py`.
Milestone 3's ADR-0002-promised mitigation — generating both from the
backend's OpenAPI schema — was never built (no generation script or
`openapi.json`-derived model exists in this repo). Until it is, a field
added here and forgotten there (or vice versa) will not be caught by any
tooling; changes to this shape must be applied to both files by hand.

Raw frames never leave the CV process (ADR 0002). Only the derived scalars
below cross the boundary.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

SCHEMA_VERSION = "1.0"


class DriverStateFrame(BaseModel):
    """One aggregated, 1 Hz observation of driver state.

    `drowsiness`, `perclos` and `blink_rate_per_min` are `None` whenever
    `face_detected` is `False` or calibration has not completed — never a
    fabricated neutral value (same discipline `TelemetryFrame`'s optional
    fields use). `distraction` is always `None` in this milestone: no
    gaze/head-pose estimation is implemented (see cv/README.md); the field
    exists because ADR 0002 names it as part of the contract, not because
    this process computes it yet.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: str = SCHEMA_VERSION
    trip_id: str
    ts: datetime

    face_detected: bool
    calibrated: bool = False

    drowsiness: float | None = Field(default=None, ge=0.0, le=1.0)
    distraction: float | None = Field(default=None, ge=0.0, le=1.0)
    perclos: float | None = Field(default=None, ge=0.0, le=1.0)
    blink_rate_per_min: float | None = Field(default=None, ge=0.0)
