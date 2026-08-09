"""Request/response schemas for the Vehicle resource."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class VehicleCreate(BaseModel):
    make: str
    model: str
    year: int
    vin: str
    license_plate: str


class VehicleUpdate(BaseModel):
    make: str | None = None
    model: str | None = None
    year: int | None = None
    vin: str | None = None
    license_plate: str | None = None


class VehicleRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    make: str
    model: str
    year: int
    vin: str
    license_plate: str
    created_at: datetime
    updated_at: datetime
