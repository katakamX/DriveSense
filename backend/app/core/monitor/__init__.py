"""Server-side driver monitoring over browser-supplied camera frames.

**This is a second, deliberately different CV path from `cv/`.** ADR 0002 puts
driver monitoring in its own process precisely so that raw frames never reach
the FastAPI worker and CPU-bound vision work never shares an event loop with
telemetry ingest. That process still exists and is still the one to use where a
camera is attached to the vehicle.

This path exists for the case that ADR 0002 does not cover: a browser, on a
phone or a laptop, with no local Python process available to run MediaPipe. The
trade-off it accepts, and which the ADR rejected for the in-vehicle case:

- Raw frames leave the client and reach the server. They are decoded, scored
  and discarded — never written to disk or to the database — but the privacy
  property ADR 0002 states ("raw frames never leave this process") does not
  hold here, and no amount of care in this package makes it hold.
- MediaPipe runs inside the API worker. Every call is dispatched to a thread
  pool so the event loop keeps serving, but the CPU is shared with ingest, and
  ADR 0003 pins the deployment to a single worker.

Neither point makes the feature wrong; both make it a different deployment
shape from the one the ADRs describe, and that is worth an ADR of its own
before this ships anywhere real.
"""

from app.core.monitor.detector import (
    DROWSY_DWELL_S,
    EAR_THRESHOLD,
    MAR_THRESHOLD,
    NOT_VISIBLE_DWELL_S,
    YAWN_DWELL_S,
    FrameDecodeError,
    MonitorResult,
    MonitorSession,
    decode_frame,
)
from app.core.monitor.geometry import (
    eye_aspect_ratio,
    mean_eye_aspect_ratio,
    mouth_aspect_ratio,
)

__all__ = [
    "DROWSY_DWELL_S",
    "EAR_THRESHOLD",
    "MAR_THRESHOLD",
    "NOT_VISIBLE_DWELL_S",
    "YAWN_DWELL_S",
    "FrameDecodeError",
    "MonitorResult",
    "MonitorSession",
    "decode_frame",
    "eye_aspect_ratio",
    "mean_eye_aspect_ratio",
    "mouth_aspect_ratio",
]
