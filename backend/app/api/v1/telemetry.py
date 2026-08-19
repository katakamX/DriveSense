"""Batched telemetry ingestion for a trip, with inline driving-event detection."""

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.events import FrameSample, detect_events, state_for
from app.core.features import FeatureSample
from app.core.live import publish
from app.core.windowing import append as buffer_append
from app.core.windowing import ensure_started
from app.db.models import DrivingEvent, Telemetry, Trip
from app.db.session import get_db
from app.schemas.live import LiveMessage
from app.schemas.telemetry import TelemetryBatchRequest, TelemetryBatchResponse

router = APIRouter(prefix="/trips/{trip_id}/telemetry", tags=["telemetry"])


def _optional_float(frame: object, name: str) -> float | None:
    """Read an extended field a producer may not send.

    `TelemetryFrameIn` allows extras, so fields this schema doesn't name (yaw
    rate, heading) arrive as attributes when the producer supplies them and
    are simply absent when it doesn't. `FeatureSample` wants `None` for a
    value nobody measured, never a fabricated zero (see its docstring).
    """
    value = getattr(frame, name, None)
    return float(value) if isinstance(value, int | float) else None


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
    # Per-trip state so a brake spanning two batches is one event, not two.
    # An event still in progress when this batch ends stays open and is
    # emitted by a later batch (or by the trip-end flush in `trips`), which
    # is why the live stream reports a harsh brake once it has finished
    # rather than at its onset — see app/core/events/state.py.
    events = detect_events(samples, speed_limit_kph, state=state_for(trip_id))
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

    # Feed the window the 1 Hz tick reduces, and start that tick if this is
    # the trip's first batch. The buffer is fed from the request payload
    # rather than from `rows` because it wants the extended fields (yaw rate,
    # heading) that the telemetry table does not have columns for — they live
    # in `raw_frame`, and re-reading them back out of JSON here would be a
    # round trip for data we are already holding.
    buffer_append(
        trip_id,
        [
            FeatureSample(
                recorded_at=frame.ts,
                speed_kph=frame.speed_kph,
                accel_ms2=frame.accel_ms2,
                lateral_accel_ms2=frame.lateral_accel_ms2,
                yaw_rate_dps=_optional_float(frame, "yaw_rate_dps"),
                heading_deg=_optional_float(frame, "heading_deg"),
                lat=frame.lat,
                lon=frame.lon,
            )
            for frame in payload.frames
        ],
    )
    ensure_started(trip_id, speed_limit_kph)

    for row, frame in zip(rows, payload.frames, strict=True):
        publish(
            trip_id,
            LiveMessage(
                type="telemetry",
                data={
                    # `seq` (a producer-assigned monotonic counter, not a DB
                    # column) rather than `recorded_at` is the latency-benchmark
                    # correlation key: a timestamp round-tripped through
                    # Postgres is not guaranteed to compare equal to the string
                    # the producer sent.
                    "seq": getattr(frame, "seq", None),
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
