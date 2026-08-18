"""Driver-facing self-service dashboard (M12).

Counterpart to `driver_applications.py`'s `/me` pattern: gated on
`get_current_user` (any logged-in user), not `require_staff`, and resolves
the driver from `Driver.user_id == current_user.id` rather than a path id.
Lives in its own router (not `trips.py`) so `GET /trips` can stay
unconditionally staff-only — this route only ever returns the caller's own
trips.
"""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user
from app.db.models import Driver, Trip, User
from app.db.session import get_db
from app.schemas.trip import TripRead

router = APIRouter(prefix="/trips", tags=["driver-dashboard"])


async def _load_driver(db: AsyncSession, user: User) -> Driver:
    result = await db.execute(select(Driver).where(Driver.user_id == user.id))
    driver = result.scalar_one_or_none()
    if driver is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No driver record found")
    return driver


@router.get("/me", response_model=list[TripRead])
async def list_my_trips(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[Trip]:
    driver = await _load_driver(db, user)
    stmt = (
        select(Trip)
        .where(Trip.driver_id == driver.id)
        .order_by(Trip.started_at.desc())
        .limit(limit)
        .offset(offset)
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())
