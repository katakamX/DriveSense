"""CRUD endpoints for Trip."""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Trip
from app.db.session import get_db
from app.schemas.trip import TripCreate, TripRead, TripUpdate

router = APIRouter(prefix="/trips", tags=["trips"])


@router.post("", response_model=TripRead, status_code=status.HTTP_201_CREATED)
async def create_trip(payload: TripCreate, db: AsyncSession = Depends(get_db)) -> Trip:
    trip = Trip(**payload.model_dump())
    db.add(trip)
    await db.commit()
    await db.refresh(trip)
    return trip


@router.get("", response_model=list[TripRead])
async def list_trips(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    driver_id: uuid.UUID | None = Query(None),
    vehicle_id: uuid.UUID | None = Query(None),
    status_: str | None = Query(None, alias="status"),
    db: AsyncSession = Depends(get_db),
) -> list[Trip]:
    stmt = select(Trip)
    if driver_id is not None:
        stmt = stmt.where(Trip.driver_id == driver_id)
    if vehicle_id is not None:
        stmt = stmt.where(Trip.vehicle_id == vehicle_id)
    if status_ is not None:
        stmt = stmt.where(Trip.status == status_)
    stmt = stmt.order_by(Trip.started_at.desc()).limit(limit).offset(offset)
    result = await db.execute(stmt)
    return list(result.scalars().all())


@router.get("/{trip_id}", response_model=TripRead)
async def get_trip(trip_id: uuid.UUID, db: AsyncSession = Depends(get_db)) -> Trip:
    trip = await db.get(Trip, trip_id)
    if trip is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Trip not found")
    return trip


@router.patch("/{trip_id}", response_model=TripRead)
async def update_trip(
    trip_id: uuid.UUID, payload: TripUpdate, db: AsyncSession = Depends(get_db)
) -> Trip:
    trip = await db.get(Trip, trip_id)
    if trip is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Trip not found")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(trip, field, value)
    await db.commit()
    await db.refresh(trip)
    return trip


@router.delete("/{trip_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_trip(trip_id: uuid.UUID, db: AsyncSession = Depends(get_db)) -> None:
    trip = await db.get(Trip, trip_id)
    if trip is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Trip not found")
    await db.delete(trip)
    await db.commit()
