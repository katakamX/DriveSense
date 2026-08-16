"""CRUD endpoints for Vehicle."""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import require_staff
from app.db.models import Vehicle
from app.db.session import get_db
from app.schemas.vehicle import VehicleCreate, VehicleRead, VehicleUpdate

router = APIRouter(prefix="/vehicles", tags=["vehicles"], dependencies=[Depends(require_staff)])

# Maps the unique-constraint name Postgres reports in IntegrityError.orig to
# the field name it protects, so a constraint violation can be turned into a
# 409 that names the actual offending field instead of a bare 500.
_UNIQUE_CONSTRAINT_FIELDS = {
    "uq_vehicles_vin": "vin",
    "uq_vehicles_license_plate": "license_plate",
}


def _conflict_field(error: IntegrityError) -> str | None:
    diag = getattr(getattr(error.orig, "diag", None), "constraint_name", None)
    return _UNIQUE_CONSTRAINT_FIELDS.get(diag)


@router.post("", response_model=VehicleRead, status_code=status.HTTP_201_CREATED)
async def create_vehicle(payload: VehicleCreate, db: AsyncSession = Depends(get_db)) -> Vehicle:
    vehicle = Vehicle(**payload.model_dump())
    db.add(vehicle)
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        field = _conflict_field(exc)
        detail = f"{field} already exists" if field else "Vehicle conflicts with an existing record"
        raise HTTPException(status.HTTP_409_CONFLICT, detail) from exc
    await db.refresh(vehicle)
    return vehicle


@router.get("", response_model=list[VehicleRead])
async def list_vehicles(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    make: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
) -> list[Vehicle]:
    stmt = select(Vehicle)
    if make is not None:
        stmt = stmt.where(Vehicle.make == make)
    stmt = stmt.order_by(Vehicle.created_at).limit(limit).offset(offset)
    result = await db.execute(stmt)
    return list(result.scalars().all())


@router.get("/{vehicle_id}", response_model=VehicleRead)
async def get_vehicle(vehicle_id: uuid.UUID, db: AsyncSession = Depends(get_db)) -> Vehicle:
    vehicle = await db.get(Vehicle, vehicle_id)
    if vehicle is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Vehicle not found")
    return vehicle


@router.patch("/{vehicle_id}", response_model=VehicleRead)
async def update_vehicle(
    vehicle_id: uuid.UUID, payload: VehicleUpdate, db: AsyncSession = Depends(get_db)
) -> Vehicle:
    vehicle = await db.get(Vehicle, vehicle_id)
    if vehicle is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Vehicle not found")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(vehicle, field, value)
    await db.commit()
    await db.refresh(vehicle)
    return vehicle


@router.delete("/{vehicle_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_vehicle(vehicle_id: uuid.UUID, db: AsyncSession = Depends(get_db)) -> None:
    vehicle = await db.get(Vehicle, vehicle_id)
    if vehicle is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Vehicle not found")
    await db.delete(vehicle)
    await db.commit()
