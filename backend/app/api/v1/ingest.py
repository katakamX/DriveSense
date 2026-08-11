"""Driver-state ingestion from the separate CV process (ADR 0002).

Unlike telemetry, this is not nested under `/trips/{trip_id}` — the CV
process is not trip-aware in the same way a telemetry producer is, so
`trip_id` travels in the payload instead of the path, matching
`DriverStateFrame`'s shape in `cv/contracts.py`.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.live import publish
from app.db.models import DriverState, Trip
from app.db.session import get_db
from app.schemas.driver_state import DriverStateIn, DriverStateResponse
from app.schemas.live import LiveMessage

router = APIRouter(prefix="/ingest", tags=["ingest"])


@router.post(
    "/driver-state", response_model=DriverStateResponse, status_code=status.HTTP_201_CREATED
)
async def ingest_driver_state(
    payload: DriverStateIn, db: AsyncSession = Depends(get_db)
) -> DriverStateResponse:
    try:
        trip_id = uuid.UUID(payload.trip_id)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "trip_id is not a UUID") from exc

    trip = await db.get(Trip, trip_id)
    if trip is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Trip not found")

    row = DriverState(
        trip_id=trip_id,
        recorded_at=payload.ts,
        schema_version=payload.schema_version,
        face_detected=payload.face_detected,
        calibrated=payload.calibrated,
        drowsiness=payload.drowsiness,
        distraction=payload.distraction,
        perclos=payload.perclos,
        blink_rate_per_min=payload.blink_rate_per_min,
    )
    db.add(row)
    await db.commit()

    publish(
        trip_id,
        LiveMessage(
            type="driver_state",
            data={
                "recorded_at": row.recorded_at.isoformat(),
                "face_detected": row.face_detected,
                "calibrated": row.calibrated,
                "drowsiness": row.drowsiness,
                "distraction": row.distraction,
                "perclos": row.perclos,
                "blink_rate_per_min": row.blink_rate_per_min,
            },
        ).model_dump(mode="json"),
    )

    return DriverStateResponse(accepted=True)
