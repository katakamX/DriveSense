"""Batched telemetry ingestion for a trip, with inline driving-event detection."""

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.events import FrameSample, detect_events
from app.core.live import publish
from app.db.models import DrivingEvent, Telemetry, Trip
from app.db.session import get_db
from app.schemas.live import LiveMessage
from app.schemas.telemetry import TelemetryBatchRequest, TelemetryBatchResponse

router = APIRouter(prefix="/trips/{trip_id}/telemetry", tags=["telemetry"])


@router.post("/batch", response_model=TelemetryBatchResponse, status_code=status.HTTP_201_CREATED)
async def ingest_telemetry_batch(
    trip_id: uuid.UUID, payload: TelemetryBatchRequest, db: AsyncSession = Depends(get_db)
) -> TelemetryBatchResponse:
    trip = await db.get(Trip, trip_id)
    if trip is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Trip not found")

    rows = [
        Telemetry(
            trip_id=trip_id,
            recorded_at=frame.ts,
            schema_version=frame.schema_version,
            speed_kph=frame.speed_kph,
            accel_ms2=frame.accel_ms2,
            lateral_accel_ms2=frame.lateral_accel_ms2,
            lat=frame.lat,
            lon=frame.lon,
            raw_frame=frame.model_dump(mode="json"),
        )
        for frame in payload.frames
    ]
    db.add_all(rows)
    await db.flush()  # assigns telemetry ids without committing, for event FK linkage

    speed_limit_kph = float(trip.speed_limit_kph or get_settings().default_speed_limit_kph)
    samples = [
        FrameSample(
            telemetry_id=row.id,
            recorded_at=row.recorded_at,
            accel_ms2=row.accel_ms2,
            speed_kph=row.speed_kph,
        )
        for row in rows
    ]
    events = detect_events(samples, speed_limit_kph)
    event_rows = [
        DrivingEvent(
            trip_id=trip_id,
            telemetry_id=event.telemetry_id,
            event_type=event.event_type,
            occurred_at=event.recorded_at,
            measured_value=event.measured_value,
            threshold_value=event.threshold_value,
        )
        for event in events
    ]
    db.add_all(event_rows)

    await db.commit()

    for row in rows:
        publish(
            trip_id,
            LiveMessage(
                type="telemetry",
                data={
                    "recorded_at": row.recorded_at.isoformat(),
                    "speed_kph": row.speed_kph,
                    "accel_ms2": row.accel_ms2,
                    "lateral_accel_ms2": row.lateral_accel_ms2,
                    "lat": row.lat,
                    "lon": row.lon,
                },
            ).model_dump(mode="json"),
        )
    for event_row in event_rows:
        publish(
            trip_id,
            LiveMessage(
                type="event",
                data={
                    "event_type": event_row.event_type,
                    "occurred_at": event_row.occurred_at.isoformat(),
                    "measured_value": event_row.measured_value,
                    "threshold_value": event_row.threshold_value,
                },
            ).model_dump(mode="json"),
        )

    return TelemetryBatchResponse(accepted=len(rows))
