"""Live WebSocket relay for a trip's telemetry and driving events.

## Three concurrent jobs, not one loop

The relay used to be a single `while True: send(await queue.get())`. That loop
is correct only for the messages it forwards, and wrong for everything else a
long-lived socket has to handle:

- **It never reads.** A WebSocket close arrives as an incoming frame, so a loop
  that only ever sends learns nothing about a client that has gone away. It
  finds out when a send fails — which, on a trip that is not currently pushing
  anything, is never. The connection and its subscriber queue stay in
  `broadcaster._subscribers` for the life of the process, and `publish` goes on
  fanning out to a socket nobody is holding.
- **It never speaks unprompted.** A half-open connection — a laptop asleep, a
  proxy that dropped an idle tunnel — is indistinguishable from a quiet trip
  from the browser's side. It goes on showing the last numbers it received
  under a "Live" label, indefinitely.

So the connection runs three tasks and lives exactly as long as the first one
to finish: the relay pump, a heartbeat, and a reader whose only purpose is to
notice the close. `asyncio.wait(FIRST_COMPLETED)` and then cancel the rest —
whichever one ends, the connection is over, and `unsubscribe` runs in a
`finally` that no path can skip.
"""

import asyncio
import contextlib
import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.live import subscribe, unsubscribe
from app.core.live.snapshot import build_snapshot
from app.db.models import Trip
from app.db.session import get_db
from app.schemas.live import LiveMessage

logger = logging.getLogger(__name__)

router = APIRouter(tags=["live"])

# Well under the 30–60 s idle timeout typical of proxies and load balancers, so
# a connection that is merely quiet is never mistaken for a dead one by
# something in the middle. The client's own staleness threshold is set to
# comfortably more than this, so a single missed ping is not a disconnect.
PING_INTERVAL_S = 20.0


@router.websocket("/trips/{trip_id}/live")
async def trip_live(
    websocket: WebSocket, trip_id: uuid.UUID, db: AsyncSession = Depends(get_db)
) -> None:
    trip = await db.get(Trip, trip_id)
    if trip is None:
        # Terminal, and the client is expected to treat it as such: retrying a
        # trip that does not exist fails identically forever.
        await websocket.close(code=4404)
        return

    await websocket.accept()
    queue = subscribe(trip_id)
    try:
        await _send(websocket, LiveMessage(type="snapshot", data=await build_snapshot(db, trip_id)))
        await _serve(websocket, queue)
    except WebSocketDisconnect:
        pass
    finally:
        unsubscribe(trip_id, queue)


async def _serve(websocket: WebSocket, queue: asyncio.Queue[dict[str, Any]]) -> None:
    """Run the three connection tasks until one of them ends, then stop them all."""
    tasks = [
        asyncio.create_task(_pump(websocket, queue), name="live-pump"),
        asyncio.create_task(_heartbeat(websocket), name="live-heartbeat"),
        asyncio.create_task(_watch_for_close(websocket), name="live-watch"),
    ]
    try:
        done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    finally:
        for task in tasks:
            task.cancel()
        # Gathered rather than left dangling: an un-awaited cancelled task logs
        # "Task exception was never retrieved" at shutdown, and worse, could
        # still be mid-`send` on a socket the caller is about to close.
        await asyncio.gather(*tasks, return_exceptions=True)

    # Re-raise whatever ended the connection so the caller's handler can tell a
    # clean disconnect from a real fault. Cancellation is not a fault.
    for task in done:
        with contextlib.suppress(asyncio.CancelledError):
            error = task.exception()
            if error is not None:
                raise error


async def _pump(websocket: WebSocket, queue: asyncio.Queue[dict[str, Any]]) -> None:
    """Forward broadcast messages. Already-serialised dicts, so no re-validation."""
    while True:
        await websocket.send_json(await queue.get())


async def _heartbeat(websocket: WebSocket) -> None:
    while True:
        await asyncio.sleep(PING_INTERVAL_S)
        await _send(
            websocket, LiveMessage(type="ping", data={"sent_at": datetime.now(UTC).isoformat()})
        )


async def _watch_for_close(websocket: WebSocket) -> None:
    """Read and discard, so the disconnect frame is actually observed.

    Nothing on this socket is client-to-server: the browser talks to the API
    over HTTP. Incoming frames are dropped rather than parsed, both because
    there is no message this endpoint accepts and because parsing input nobody
    is supposed to send is how an endpoint acquires an attack surface it never
    meant to have.
    """
    while True:
        message = await websocket.receive()
        if message["type"] == "websocket.disconnect":
            raise WebSocketDisconnect(message.get("code", 1000))


async def _send(websocket: WebSocket, message: LiveMessage) -> None:
    await websocket.send_json(message.model_dump(mode="json"))
