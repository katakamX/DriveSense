"""CRUD endpoints for Trip."""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import require_staff
from app.core.events import discard_trip, flush_trip
from app.core.live import publish
from app.core.risk import sink as risk_sink
from app.core.windowing import stop_trip
from app.db.models import DrivingEvent, Trip
from app.db.session import get_db
from app.schemas.live import LiveMessage
from app.schemas.trip import TripCreate, TripRead, TripUpdate

# A trip in one of these is over, so any event still open in the debounce
# state machine has to be closed and persisted rather than left dangling.
TERMINAL_TRIP_STATUSES = frozenset({"completed", "ended", "aborted", "cancelled"})

router = APIRouter(prefix="/trips", tags=["trips"], dependencies=[Depends(require_staff)])


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
    changes = payload.model_dump(exclude_unset=True)
    for field, value in changes.items():
        setattr(trip, field, value)

    ending = changes.get("ended_at") is not None or (
        changes.get("status") in TERMINAL_TRIP_STATUSES
    )
    trailing = flush_trip(trip_id) if ending else []
    if ending:
        # Same discipline as the detector-state flush above: a trip that is
        # over holds no in-process state. Cancels the tick and waits for it,
        # then releases the buffer.
        await stop_trip(trip_id)
        # Strictly after `stop_trip`, which awaits the tick's cancellation:
        # a tick still running here could enqueue an assessment after the
        # flush had already read the queue, and that row would be lost.
        # Passing this request's session puts the trailing risk rows and the
        # trip's summary columns in the same transaction as its status change.
        await risk_sink.finalise_trip(trip_id, session=db)
    for event in trailing:
        db.add(
            DrivingEvent(
                trip_id=trip_id,
                telemetry_id=event.telemetry_id,
                event_type=event.event_type,
                occurred_at=event.recorded_at,
                measured_value=event.measured_value,
                threshold_value=event.threshold_value,
            )
        )

    await db.commit()
    await db.refresh(trip)

    for event in trailing:
        publish(
            trip_id,
            LiveMessage(
                type="event",
                data={
                    "event_type": event.event_type,
                    "occurred_at": event.recorded_at.isoformat(),
                    "measured_value": event.measured_value,
                    "threshold_value": event.threshold_value,
                },
            ).model_dump(mode="json"),
        )
    return trip


@router.delete("/{trip_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_trip(trip_id: uuid.UUID, db: AsyncSession = Depends(get_db)) -> None:
    trip = await db.get(Trip, trip_id)
    if trip is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Trip not found")
    # Drop the sink's pending rows *before* the delete: they carry this
    # trip_id as a foreign key, and a flush racing the delete would insert
    # rows referencing a trip that no longer exists.
    risk_sink.discard_trip(trip_id)
    await db.delete(trip)
    await db.commit()
    discard_trip(trip_id)
    await stop_trip(trip_id)
    # Again after the tick has been awaited to a stop, since a final tick
    # could have enqueued between the first call and the cancellation.
    risk_sink.discard_trip(trip_id)
