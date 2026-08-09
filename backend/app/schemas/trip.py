"""Request/response schemas for the Trip resource."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class TripCreate(BaseModel):
    driver_id: uuid.UUID
    vehicle_id: uuid.UUID
    started_at: datetime
    ended_at: datetime | None = None
    distance_km: float | None = None
    status: str = "in_progress"


class TripUpdate(BaseModel):
    ended_at: datetime | None = None
    distance_km: float | None = None
    status: str | None = None


class TripRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    driver_id: uuid.UUID
    vehicle_id: uuid.UUID
    started_at: datetime
    ended_at: datetime | None
    distance_km: float | None
    status: str
    created_at: datetime
    updated_at: datetime
