"""Batched telemetry ingestion for a trip."""

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Telemetry, Trip
from app.db.session import get_db
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
    await db.commit()
    return TelemetryBatchResponse(accepted=len(rows))
