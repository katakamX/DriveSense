"""Request/response schemas for the Driver resource."""

import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, field_validator


# Codes are stored upper-cased so the `?code=` filter's case-insensitive
# match (app/api/v1/drivers.py) is a plain equality check, not a citext
# column or a LOWER() index.
def _upper_or_none(value: str | None) -> str | None:
    return value.upper() if value is not None else None


class DriverCreate(BaseModel):
    name: str
    license_number: str
    date_of_birth: date
    driver_code: str | None = None
    current_vehicle_id: uuid.UUID | None = None

    _normalise_driver_code = field_validator("driver_code")(_upper_or_none)


class DriverUpdate(BaseModel):
    name: str | None = None
    license_number: str | None = None
    date_of_birth: date | None = None
    driver_code: str | None = None
    current_vehicle_id: uuid.UUID | None = None

    _normalise_driver_code = field_validator("driver_code")(_upper_or_none)


class DriverVehicleRead(BaseModel):
    """Vehicle summary embedded in `DriverRead`, not the full `VehicleRead`.

    A driver lookup needs enough to identify the vehicle in a UI, not its VIN
    or record timestamps — those belong to `GET /vehicles/{id}` if ever needed.
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    make: str
    model: str
    license_plate: str


class DriverRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    license_number: str
    date_of_birth: date
    driver_code: str | None
    current_vehicle: DriverVehicleRead | None
    created_at: datetime
    updated_at: datetime
