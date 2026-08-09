"""CRUD endpoints for Driver."""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Driver
from app.db.session import get_db
from app.schemas.driver import DriverCreate, DriverRead, DriverUpdate

router = APIRouter(prefix="/drivers", tags=["drivers"])


@router.post("", response_model=DriverRead, status_code=status.HTTP_201_CREATED)
async def create_driver(payload: DriverCreate, db: AsyncSession = Depends(get_db)) -> Driver:
    driver = Driver(**payload.model_dump())
    db.add(driver)
    await db.commit()
    await db.refresh(driver)
    return driver


@router.get("", response_model=list[DriverRead])
async def list_drivers(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    name: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
) -> list[Driver]:
    stmt = select(Driver)
    if name is not None:
        stmt = stmt.where(Driver.name == name)
    stmt = stmt.order_by(Driver.created_at).limit(limit).offset(offset)
    result = await db.execute(stmt)
    return list(result.scalars().all())


@router.get("/{driver_id}", response_model=DriverRead)
async def get_driver(driver_id: uuid.UUID, db: AsyncSession = Depends(get_db)) -> Driver:
    driver = await db.get(Driver, driver_id)
    if driver is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Driver not found")
    return driver


@router.patch("/{driver_id}", response_model=DriverRead)
async def update_driver(
    driver_id: uuid.UUID, payload: DriverUpdate, db: AsyncSession = Depends(get_db)
) -> Driver:
    driver = await db.get(Driver, driver_id)
    if driver is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Driver not found")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(driver, field, value)
    await db.commit()
    await db.refresh(driver)
    return driver


@router.delete("/{driver_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_driver(driver_id: uuid.UUID, db: AsyncSession = Depends(get_db)) -> None:
    driver = await db.get(Driver, driver_id)
    if driver is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Driver not found")
    await db.delete(driver)
    await db.commit()
