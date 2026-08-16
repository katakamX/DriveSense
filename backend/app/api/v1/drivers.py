"""CRUD endpoints for Driver."""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.deps import require_staff
from app.db.models import Driver
from app.db.session import get_db
from app.schemas.driver import DriverCreate, DriverRead, DriverUpdate

router = APIRouter(prefix="/drivers", tags=["drivers"], dependencies=[Depends(require_staff)])

# Maps the unique-constraint name Postgres reports in IntegrityError.orig to
# the field name it protects, so a constraint violation can be turned into a
# 409 that names the actual offending field instead of a bare 500.
_UNIQUE_CONSTRAINT_FIELDS = {
    "uq_drivers_driver_code": "driver_code",
    "uq_drivers_license_number": "license_number",
}


def _conflict_field(error: IntegrityError) -> str | None:
    diag = getattr(getattr(error.orig, "diag", None), "constraint_name", None)
    return _UNIQUE_CONSTRAINT_FIELDS.get(diag)


@router.post("", response_model=DriverRead, status_code=status.HTTP_201_CREATED)
async def create_driver(payload: DriverCreate, db: AsyncSession = Depends(get_db)) -> Driver:
    driver = Driver(**payload.model_dump())
    db.add(driver)
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        field = _conflict_field(exc)
        detail = f"{field} already exists" if field else "Driver conflicts with an existing record"
        raise HTTPException(status.HTTP_409_CONFLICT, detail) from exc
    # Two refreshes, not one `attribute_names=["current_vehicle"]` call: that
    # form loads only the named relationship and leaves server-generated
    # columns (`updated_at`'s `onupdate=func.now()`) at their stale
    # pre-commit value, which then triggers a lazy load outside the async
    # context when the response model reads them.
    await db.refresh(driver)
    await db.refresh(driver, attribute_names=["current_vehicle"])
    return driver


@router.get("", response_model=list[DriverRead])
async def list_drivers(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    name: str | None = Query(None),
    code: str | None = Query(None, description="Exact match on driver_code, case-insensitive"),
    db: AsyncSession = Depends(get_db),
) -> list[Driver]:
    stmt = select(Driver).options(selectinload(Driver.current_vehicle))
    if name is not None:
        stmt = stmt.where(Driver.name == name)
    if code is not None:
        stmt = stmt.where(Driver.driver_code == code.upper())
    stmt = stmt.order_by(Driver.created_at).limit(limit).offset(offset)
    result = await db.execute(stmt)
    return list(result.scalars().all())


@router.get("/{driver_id}", response_model=DriverRead)
async def get_driver(driver_id: uuid.UUID, db: AsyncSession = Depends(get_db)) -> Driver:
    driver = await db.get(Driver, driver_id, options=[selectinload(Driver.current_vehicle)])
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
    await db.refresh(driver, attribute_names=["current_vehicle"])
    return driver


@router.delete("/{driver_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_driver(driver_id: uuid.UUID, db: AsyncSession = Depends(get_db)) -> None:
    driver = await db.get(Driver, driver_id)
    if driver is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Driver not found")
    await db.delete(driver)
    await db.commit()
