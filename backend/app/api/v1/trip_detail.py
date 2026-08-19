"""Read-only trip detail sub-resources: risk breakdown, events, route (M12 page 2).

Gating is neither `require_staff` (trips.py) nor pure self-service
(driver_dashboard.py) but both: staff can view any trip, and a driver can
view their own trip (`Driver.user_id == current_user.id`), same ownership
check as `driver_dashboard.list_my_trips`. Lives in its own router, keyed
by `trip_id` rather than `driver_id`, so the check is written once here
(`_trip_for_viewer`) and shared by all three endpoints instead of repeated.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import STAFF_ROLES, get_current_user
from app.db.models import Driver, DrivingEvent, RiskWindow, Telemetry, Trip, User
from app.db.session import get_db
from app.schemas.trip_detail import DrivingEventRead, RiskWindowRead, TelemetryPointRead

router = APIRouter(prefix="/trips/{trip_id}", tags=["trip-detail"])


async def _trip_for_viewer(
    trip_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Trip:
    trip = await db.get(Trip, trip_id)
    if trip is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Trip not found")
    if user.role in STAFF_ROLES:
        return trip
    result = await db.execute(select(Driver).where(Driver.user_id == user.id))
    driver = result.scalar_one_or_none()
    if driver is not None and driver.id == trip.driver_id:
        return trip
    # Same "wrong owner reads as missing" answer as driver_review.py's
    # document endpoint: a trip that exists but isn't staff-visible and
    # isn't the caller's own is reported as not found, not forbidden.
    raise HTTPException(status.HTTP_404_NOT_FOUND, "Trip not found")


@router.get("/risk-windows", response_model=list[RiskWindowRead])
async def list_risk_windows(
    trip: Trip = Depends(_trip_for_viewer),
    db: AsyncSession = Depends(get_db),
) -> list[RiskWindow]:
    stmt = select(RiskWindow).where(RiskWindow.trip_id == trip.id).order_by(RiskWindow.window_start)
    result = await db.execute(stmt)
    return list(result.scalars().all())


@router.get("/events", response_model=list[DrivingEventRead])
async def list_trip_events(
    trip: Trip = Depends(_trip_for_viewer),
    db: AsyncSession = Depends(get_db),
) -> list[DrivingEvent]:
    stmt = (
        select(DrivingEvent)
        .where(DrivingEvent.trip_id == trip.id)
        .order_by(DrivingEvent.occurred_at)
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())


@router.get("/telemetry", response_model=list[TelemetryPointRead])
async def list_trip_telemetry(
    trip: Trip = Depends(_trip_for_viewer),
    db: AsyncSession = Depends(get_db),
) -> list[Telemetry]:
    stmt = select(Telemetry).where(Telemetry.trip_id == trip.id).order_by(Telemetry.recorded_at)
    result = await db.execute(stmt)
    return list(result.scalars().all())
