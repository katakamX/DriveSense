"""Per-session drowsiness/yawn state, and the frame decode that feeds it.

The unit of state is one WebSocket connection: one driver, one camera, one
`MonitorSession`. Nothing here is shared between connections and nothing
outlives one, which is why this module has no registry and no cleanup hook —
the socket handler owns the object and drops it when the socket closes.

## Why sustained conditions rather than per-frame thresholds

A single frame below the EAR threshold is a blink, a glance down, or landmark
noise on a 320-pixel-wide JPEG. Alerting on it would produce an alarm several
times a minute for a fully alert driver, which is worse than no alarm at all:
the driver learns to ignore it. So each condition has to hold *continuously*
for a dwell time before it is reported, and any frame that breaks the
condition resets the clock.

The dwell is measured in wall-clock seconds, not in frames. The browser sends
at a nominal 5 fps, but a busy tab, a slow network or a dropped frame all move
the real rate around, and a frame-counted dwell would silently mean different
things at different rates.

## What a fixed EAR threshold can and cannot do

`SESSION_EAR_CAVEAT` below is not decoration. EAR is person-specific: eye
shape, glasses and camera angle all shift the absolute value, so 0.21 is a
reasonable starting point and not a calibrated one. `cv/drowsiness.py` solves
this with a neutral-face calibration at session start and scores against a
fraction of the measured baseline. This path deliberately does not, because
the caller asked for fixed thresholds — but the number that comes out is a
threshold crossing, not a measurement of alertness, and it should not be
presented to a driver as the latter.
"""

from __future__ import annotations

import base64
import binascii
import logging
from dataclasses import dataclass
from typing import cast

import cv2
import numpy as np
import numpy.typing as npt

from app.core.monitor.geometry import mean_eye_aspect_ratio, mouth_aspect_ratio
from app.core.monitor.landmarker import FaceLandmarkExtractor

logger = logging.getLogger(__name__)

SESSION_EAR_CAVEAT = (
    "Fixed EAR threshold, not calibrated to this driver. Indicates a threshold "
    "crossing sustained over time, not a measurement of alertness."
)

# Eyes below this EAR are treated as closed. See the caveat above.
EAR_THRESHOLD = 0.21
# Seconds the eyes must stay closed before the session reports drowsiness.
DROWSY_DWELL_S = 1.5

# Mouth above this MAR is treated as open wide.
MAR_THRESHOLD = 0.6
# Seconds the mouth must stay open before the session reports a yawn.
YAWN_DWELL_S = 1.0

# Seconds without a detected face before the driver is reported not visible.
# Longer than the other two: a face is routinely lost for a frame or two when
# the driver checks a mirror, and that is not an absence.
NOT_VISIBLE_DWELL_S = 2.0


class FrameDecodeError(ValueError):
    """The inbound message did not carry a decodable JPEG."""


def decode_frame(data_url: str) -> npt.NDArray[np.uint8]:
    """Decode a `data:image/jpeg;base64,...` payload into a BGR array.

    Accepts a bare base64 string too — the `data:` prefix is what a browser's
    `canvas.toDataURL()` produces, but nothing about the rest of the pipeline
    depends on it being there.

    Raises `FrameDecodeError` rather than letting a malformed frame surface as
    a `binascii.Error` or a `None` from `cv2.imdecode` three frames later.
    """
    payload = data_url.split(",", 1)[1] if data_url.startswith("data:") else data_url
    try:
        raw = base64.b64decode(payload, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise FrameDecodeError("frame is not valid base64") from exc

    buffer = np.frombuffer(raw, dtype=np.uint8)
    if buffer.size == 0:
        raise FrameDecodeError("frame is empty")

    image = cv2.imdecode(buffer, cv2.IMREAD_COLOR)
    if image is None:
        raise FrameDecodeError("frame is not a decodable image")
    # `IMREAD_COLOR` always yields 8-bit BGR, but cv2's stubs type imdecode's
    # return as the union of every dtype it could produce under some other
    # flag. The narrowing is the flag's guarantee, not an assumption.
    return cast(npt.NDArray[np.uint8], image)


@dataclass(frozen=True)
class MonitorResult:
    """One frame's verdict.

    `ear` and `mar` are `None` when no face was found — the ratios are
    undefined without landmarks, and reporting 0.0 would be indistinguishable
    from a genuinely closed eye. Missing signals are not imputed.
    """

    face_detected: bool
    not_visible: bool
    ear: float | None
    mar: float | None
    eyes_closed: bool
    drowsy: bool
    yawning: bool


class MonitorSession:
    """Sustained-condition tracking for one driver's camera session.

    Hold one per WebSocket connection. `observe` is synchronous and CPU-bound
    (it runs MediaPipe); the caller is responsible for keeping it off the event
    loop — see `app.api.v1.driver_monitor`.
    """

    def __init__(
        self,
        extractor: FaceLandmarkExtractor | None = None,
        *,
        ear_threshold: float = EAR_THRESHOLD,
        mar_threshold: float = MAR_THRESHOLD,
        drowsy_dwell_s: float = DROWSY_DWELL_S,
        yawn_dwell_s: float = YAWN_DWELL_S,
        not_visible_dwell_s: float = NOT_VISIBLE_DWELL_S,
    ) -> None:
        self._extractor = extractor if extractor is not None else FaceLandmarkExtractor()
        self._ear_threshold = ear_threshold
        self._mar_threshold = mar_threshold
        self._drowsy_dwell_s = drowsy_dwell_s
        self._yawn_dwell_s = yawn_dwell_s
        self._not_visible_dwell_s = not_visible_dwell_s

        # Monotonic timestamp at which each condition most recently *became*
        # true, or None while it is false. Storing the onset rather than an
        # accumulated duration means a reset is a single assignment and cannot
        # drift.
        self._eyes_closed_since: float | None = None
        self._mouth_open_since: float | None = None
        self._face_missing_since: float | None = None

    def observe(self, frame_bgr: npt.NDArray[np.uint8], now_s: float) -> MonitorResult:
        """Score one frame and advance the dwell clocks.

        `now_s` is a monotonic clock reading supplied by the caller rather than
        read here, so the state machine can be tested over an arbitrary
        timeline without sleeping through it.
        """
        landmarks = self._extractor.process(frame_bgr)

        if (
            not landmarks.face_detected
            or landmarks.left_eye is None
            or landmarks.right_eye is None
            or landmarks.mouth is None
        ):
            return self._observe_no_face(now_s)

        self._face_missing_since = None

        ear = mean_eye_aspect_ratio(landmarks.left_eye, landmarks.right_eye)
        mar = mouth_aspect_ratio(landmarks.mouth)

        eyes_closed = ear < self._ear_threshold
        self._eyes_closed_since = self._advance(self._eyes_closed_since, eyes_closed, now_s)

        mouth_open = mar > self._mar_threshold
        self._mouth_open_since = self._advance(self._mouth_open_since, mouth_open, now_s)

        return MonitorResult(
            face_detected=True,
            not_visible=False,
            ear=ear,
            mar=mar,
            eyes_closed=eyes_closed,
            drowsy=self._held(self._eyes_closed_since, self._drowsy_dwell_s, now_s),
            yawning=self._held(self._mouth_open_since, self._yawn_dwell_s, now_s),
        )

    def _observe_no_face(self, now_s: float) -> MonitorResult:
        """No face this frame.

        The eye and mouth clocks are reset rather than held. A face that has
        left the frame is not a face with its eyes shut, and letting the drowsy
        clock keep running through an absence would turn "driver looked away"
        into "driver asleep" after 1.5 seconds.
        """
        self._face_missing_since = self._advance(self._face_missing_since, True, now_s)
        self._eyes_closed_since = None
        self._mouth_open_since = None
        return MonitorResult(
            face_detected=False,
            not_visible=self._held(self._face_missing_since, self._not_visible_dwell_s, now_s),
            ear=None,
            mar=None,
            eyes_closed=False,
            drowsy=False,
            yawning=False,
        )

    @staticmethod
    def _advance(since: float | None, condition: bool, now_s: float) -> float | None:
        """Start the clock on a rising edge, keep it on a hold, clear it otherwise."""
        if not condition:
            return None
        return now_s if since is None else since

    @staticmethod
    def _held(since: float | None, dwell_s: float, now_s: float) -> bool:
        return since is not None and (now_s - since) >= dwell_s

    def close(self) -> None:
        self._extractor.close()
