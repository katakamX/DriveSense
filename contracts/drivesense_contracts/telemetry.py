"""The shared telemetry contract.

Every telemetry producer emits `TelemetryFrame`; every consumer parses it.
There is exactly one definition, here, so producers and consumers cannot drift
apart (see docs/adr/0005-shared-contracts-package.md).

Optional fields are genuinely optional: not every vehicle exposes every OBD2
PID, and a missing value must be `None` rather than a fabricated zero.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

SCHEMA_VERSION = "1.0"

SourceKind = Literal["simulator", "obd2"]

# Gear encoding shared by producers: -1 reverse, 0 neutral, 1..n forward.
REVERSE_GEAR = -1
NEUTRAL_GEAR = 0


def gear_label(gear: int) -> str:
    """Human-readable gear name, used by HUDs and reports."""
    if gear == REVERSE_GEAR:
        return "R"
    if gear == NEUTRAL_GEAR:
        return "N"
    return str(gear)


class TelemetryFrame(BaseModel):
    """A single sampled observation of vehicle state.

    Timestamps are *simulated* (or, for real hardware, device) time — see
    `sim_t`. Consumers must not assume frames arrive in wall-clock real time:
    a headless dataset run produces thirty minutes of driving in seconds.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: str = SCHEMA_VERSION
    trip_id: str
    source: SourceKind
    seq: int = Field(ge=0, description="Monotonic frame counter within the trip")

    sim_t: float = Field(ge=0.0, description="Seconds since trip start, simulated time")
    ts: datetime = Field(description="Trip start instant advanced by sim_t")

    # --- Longitudinal -------------------------------------------------------
    speed_kph: float = Field(ge=-50.0, le=400.0)
    accel_ms2: float
    engine_rpm: float = Field(ge=0.0)

    # --- Driver inputs ------------------------------------------------------
    throttle_pct: float = Field(ge=0.0, le=100.0)
    brake_pct: float = Field(ge=0.0, le=100.0)
    clutch_pct: float = Field(ge=0.0, le=100.0, description="100 = fully disengaged")
    gear: int = Field(ge=-1)

    # --- Engine -------------------------------------------------------------
    engine_load_pct: float = Field(ge=0.0, le=100.0)
    engine_on: bool = True
    rev_limiter_active: bool = False

    # --- Lateral ------------------------------------------------------------
    steering_deg: float
    yaw_rate_dps: float
    lateral_accel_ms2: float
    heading_deg: float = Field(ge=0.0, lt=360.0)

    # --- Trip ---------------------------------------------------------------
    distance_m: float = Field(ge=0.0)

    # --- Optional / not universally available -------------------------------
    lat: float | None = Field(default=None, ge=-90.0, le=90.0)
    lon: float | None = Field(default=None, ge=-180.0, le=180.0)
    coolant_c: float | None = None

    @property
    def gear_label(self) -> str:
        return gear_label(self.gear)


class TripMeta(BaseModel):
    """Sidecar metadata describing how a recording was produced.

    Without this a recording cannot be reproduced or trusted six weeks later,
    which matters directly for the ML milestones.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: str = SCHEMA_VERSION
    trip_id: str
    source: SourceKind
    started_at: datetime
    sample_rate_hz: float = Field(gt=0.0)
    generator: str
    generator_version: str
    git_sha: str | None = None
    vehicle: dict[str, Any] = Field(default_factory=dict)
    config: dict[str, Any] = Field(default_factory=dict)
