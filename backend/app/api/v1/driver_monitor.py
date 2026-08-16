"""WebSocket endpoint for browser-camera driver monitoring.

One connection is one camera session: it owns a `MonitorSession` (and through
it one MediaPipe landmarker), created on accept and closed in `finally`. There
is no registry and no cross-connection state, so nothing here needs the
lifespan teardown that `app.core.windowing` and `app.core.risk.sink` do.

Unlike `app.api.v1.live`, this socket is a *dialogue*: the client sends a
frame, the server scores it and answers. That is why it reads in a loop rather
than draining a broadcast queue, and why a client that stops sending is
detected immediately rather than at the next publish.

See `app.core.monitor`'s package docstring for how this path relates to — and
departs from — ADR 0002's separate CV process.
"""

import logging
import time
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import ValidationError
from starlette.concurrency import run_in_threadpool

from app.core.monitor import FrameDecodeError, MonitorResult, MonitorSession, decode_frame
from app.schemas.monitor import MonitorError, MonitorFrame, MonitorReading

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ws", tags=["driver-monitor"])

# A driver code is an opaque client-supplied label on this socket — the lookup
# that turns it into a driver is the frontend's, and stubbed there for now. It
# is still bounded here: it is echoed back in every response, and an unbounded
# string from an unauthenticated socket has no business being reflected.
MAX_DRIVER_CODE_LENGTH = 64


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


@router.websocket("/driver-monitor/{driver_code}")
async def driver_monitor(websocket: WebSocket, driver_code: str) -> None:
    if not driver_code or len(driver_code) > MAX_DRIVER_CODE_LENGTH:
        await websocket.close(code=4400)
        return

    await websocket.accept()
    session_id = uuid.uuid4()
    logger.info("Driver monitor session %s opened for code %s", session_id, driver_code)

    # Constructing the session downloads the model bundle on a cold checkout
    # and initialises MediaPipe — both blocking, both off the event loop. It
    # happens after `accept()` so a client that is waiting on the handshake
    # sees the socket open rather than a timeout.
    try:
        session = await run_in_threadpool(MonitorSession)
    except Exception:
        logger.exception("Failed to initialise monitor session %s", session_id)
        await websocket.close(code=1011)
        return

    try:
        await _serve(websocket, session, driver_code)
    except WebSocketDisconnect:
        pass
    finally:
        await run_in_threadpool(session.close)
        logger.info("Driver monitor session %s closed", session_id)


async def _serve(websocket: WebSocket, session: MonitorSession, driver_code: str) -> None:
    while True:
        raw = await websocket.receive_json()

        try:
            message = MonitorFrame.model_validate(raw)
        except ValidationError:
            await websocket.send_json(
                MonitorError(
                    timestamp=_now_iso(),
                    driver_code=driver_code,
                    detail='message must be {"frame": "data:image/jpeg;base64,..."}',
                ).model_dump(mode="json"),
            )
            continue

        try:
            result = await run_in_threadpool(_score, session, message.frame)
        except FrameDecodeError as exc:
            await websocket.send_json(
                MonitorError(
                    timestamp=_now_iso(), driver_code=driver_code, detail=str(exc)
                ).model_dump(mode="json"),
            )
            continue
        except Exception:
            # One bad frame must not end the session — the same reasoning as
            # the inference tick's except: this costs 200 ms of monitoring
            # rather than the rest of the drive's.
            logger.exception("Driver monitor frame failed for code %s", driver_code)
            await websocket.send_json(
                MonitorError(
                    timestamp=_now_iso(),
                    driver_code=driver_code,
                    detail="frame could not be scored",
                ).model_dump(mode="json"),
            )
            continue

        await websocket.send_json(
            MonitorReading(
                timestamp=_now_iso(),
                driver_code=driver_code,
                face_detected=result.face_detected,
                not_visible=result.not_visible,
                ear=result.ear,
                mar=result.mar,
                eyes_closed=result.eyes_closed,
                drowsy=result.drowsy,
                yawning=result.yawning,
            ).model_dump(mode="json"),
        )


def _score(session: MonitorSession, frame: str) -> MonitorResult:
    """Decode and score one frame. Runs in a worker thread.

    Decode and detection are one unit of work so a frame crosses the thread
    boundary once rather than twice. The dwell clock is read here, inside the
    worker, because the meaningful instant is when the frame was *scored* —
    reading it on the event loop before dispatch would fold queueing delay
    into the dwell times, making a busy server report drowsiness sooner.
    """
    image = decode_frame(frame)
    return session.observe(image, time.monotonic())
