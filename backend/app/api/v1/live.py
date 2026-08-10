"""Live WebSocket relay for a trip's telemetry and driving events."""

import uuid

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.live import subscribe, unsubscribe
from app.db.models import Trip
from app.db.session import get_db

router = APIRouter(tags=["live"])


@router.websocket("/trips/{trip_id}/live")
async def trip_live(
    websocket: WebSocket, trip_id: uuid.UUID, db: AsyncSession = Depends(get_db)
) -> None:
    trip = await db.get(Trip, trip_id)
    if trip is None:
        await websocket.close(code=4404)
        return

    await websocket.accept()
    queue = subscribe(trip_id)
    try:
        while True:
            message = await queue.get()
            await websocket.send_json(message)
    except WebSocketDisconnect:
        pass
    finally:
        unsubscribe(trip_id, queue)
