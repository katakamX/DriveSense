"""Wire contract for the browser-camera driver-monitor socket.

Separate from `schemas/live.py` because it is a different conversation: the
trip socket is server-push only, this one is a request/response exchange with
a frame going up and a verdict coming back. Folding both into one envelope
would mean a `LiveMessage` type that only ever appears on a socket the trip
stream does not use.
"""

from typing import Literal

from pydantic import BaseModel, Field

#: Generous ceiling for a base64 JPEG at the client's capture width (320px,
#: quality 0.7 — see `useDriverMonitor.ts`), which runs a few tens of KB.
#: This exists to reject an oversized or malicious payload before it reaches
#: `decode_frame`, not to accommodate any frame this client actually sends.
MAX_FRAME_LENGTH = 2_000_000


class MonitorFrame(BaseModel):
    """One inbound frame from the browser.

    `frame` is a `data:image/jpeg;base64,...` URL as produced by
    `canvas.toDataURL('image/jpeg', …)`; a bare base64 string is accepted too.
    """

    frame: str = Field(min_length=1, max_length=MAX_FRAME_LENGTH)


class MonitorReading(BaseModel):
    """One frame's verdict, pushed back per frame received.

    `ear` and `mar` are null when no face was found rather than zero — a
    ratio has no value without landmarks, and zero is what a shut eye looks
    like. See `app.core.monitor.detector`.
    """

    type: Literal["reading"] = "reading"
    timestamp: str
    driver_code: str
    face_detected: bool
    not_visible: bool
    ear: float | None
    mar: float | None
    eyes_closed: bool
    drowsy: bool
    yawning: bool


class MonitorError(BaseModel):
    """A frame that could not be scored.

    Sent instead of a reading, so a client that gets neither knows the socket
    itself is the problem. Never fatal to the connection: one unreadable frame
    at 5 fps is 200 ms, and dropping the session over it would be a worse
    failure than skipping it.
    """

    type: Literal["error"] = "error"
    timestamp: str
    driver_code: str
    detail: str
