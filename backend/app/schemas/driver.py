"""Request/response schemas for the Driver resource."""

import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict


class DriverCreate(BaseModel):
    name: str
    license_number: str
    date_of_birth: date


class DriverUpdate(BaseModel):
    name: str | None = None
    license_number: str | None = None
    date_of_birth: date | None = None


class DriverRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    license_number: str
    date_of_birth: date
    created_at: datetime
    updated_at: datetime
