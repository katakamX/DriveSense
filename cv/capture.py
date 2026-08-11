"""Camera acquisition loop (OpenCV `VideoCapture`).

CV is optional (ADR 0002): a missing or disconnected camera must not crash
this process. `frames()` logs clearly and stops iterating rather than
raising, so `main.py` can catch the end of iteration and exit (or, in a
supervised deployment, be restarted) instead of dying on an exception.
"""

from __future__ import annotations

import logging
import sys
import time
from collections.abc import Iterator

import cv2
import numpy as np
import numpy.typing as npt

logger = logging.getLogger(__name__)

# Consecutive unreadable frames tolerated before treating the camera as
# disconnected. A single dropped frame is normal; this is not that.
MAX_CONSECUTIVE_READ_FAILURES = 30

# On Windows, OpenCV's default backend is Media Foundation (MSMF), which on
# some webcams opens the device without the sensor ever coming up — no LED,
# and frames that are uniformly black. DirectShow is the more reliable
# backend there. Elsewhere, let OpenCV pick (CAP_DSHOW is Windows-only).
DEFAULT_BACKEND = cv2.CAP_DSHOW if sys.platform == "win32" else cv2.CAP_ANY

# Frames to sample when checking that the sensor is really producing an
# image. Some cameras hand back a few blank frames while auto-exposure
# settles, so one uniform frame is not yet evidence of a problem.
SENSOR_PROBE_FRAMES = 5

# Per-pixel standard deviation below which a frame is considered uniform
# (all-black, all-white, or a flat test pattern) rather than a real image.
UNIFORM_FRAME_STD = 1.0


class Camera:
    def __init__(self, device_index: int = 0, backend: int = DEFAULT_BACKEND) -> None:
        self.device_index = device_index
        self.backend = backend
        self._cap: cv2.VideoCapture | None = None

    def open(self) -> bool:
        self._cap = cv2.VideoCapture(self.device_index, self.backend)
        if not self._cap.isOpened():
            # `getBackendName()` is not safe to call on a closed capture, so
            # report the requested backend id instead.
            logger.error(
                "Camera %s could not be opened (requested backend %s)",
                self.device_index,
                self.backend,
            )
            self._cap.release()
            self._cap = None
            return False
        logger.info("Camera %s opened (backend %s)", self.device_index, self._cap.getBackendName())
        self._check_sensor_active()
        return True

    def _check_sensor_active(self) -> bool:
        """Warn if the opened device is not producing a real image.

        A handle that opens but only yields uniform frames means the sensor
        never actually started. That is a warning, not a failure: capture
        proceeds so a genuinely dark scene is never mistaken for a fault.
        """
        assert self._cap is not None

        last_std = None
        last_mean = None
        for _ in range(SENSOR_PROBE_FRAMES):
            ok, frame = self._cap.read()
            if not ok or frame is None:
                continue
            last_std = float(frame.std())
            last_mean = float(frame.mean())
            if last_std >= UNIFORM_FRAME_STD:
                return True

        if last_std is None:
            logger.warning(
                "Camera %s opened but returned no frames in %d attempts; "
                "the sensor may not be active",
                self.device_index,
                SENSOR_PROBE_FRAMES,
            )
        else:
            logger.warning(
                "Camera %s is returning uniform frames (mean=%.1f, std=%.2f over %d frames); "
                "the sensor may not be active, or the lens is covered",
                self.device_index,
                last_mean,
                last_std,
                SENSOR_PROBE_FRAMES,
            )
        return False

    def frames(self, target_fps: float = 15.0) -> Iterator[npt.NDArray[np.uint8]]:
        """Yield BGR frames, self-pacing to `target_fps`.

        Stops (without raising) after `MAX_CONSECUTIVE_READ_FAILURES`
        consecutive failed reads — the camera was disconnected mid-session.
        """
        if self._cap is None and not self.open():
            return

        assert self._cap is not None
        frame_interval_s = 1.0 / target_fps
        consecutive_failures = 0

        while True:
            loop_start = time.monotonic()
            ok, frame = self._cap.read()
            if not ok:
                consecutive_failures += 1
                logger.warning(
                    "Camera %s frame read failed (%d/%d)",
                    self.device_index,
                    consecutive_failures,
                    MAX_CONSECUTIVE_READ_FAILURES,
                )
                if consecutive_failures >= MAX_CONSECUTIVE_READ_FAILURES:
                    logger.error(
                        "Camera %s appears disconnected; stopping capture", self.device_index
                    )
                    return
                continue

            consecutive_failures = 0
            # `VideoCapture.read()` is typed to return the broader `MatLike`
            # (mypy has no way to know a webcam only ever hands back 8-bit
            # BGR); `copy=False` makes this a no-op cast on the actual data.
            yield frame.astype(np.uint8, copy=False)

            elapsed = time.monotonic() - loop_start
            remaining = frame_interval_s - elapsed
            if remaining > 0:
                time.sleep(remaining)

    def release(self) -> None:
        if self._cap is not None:
            self._cap.release()
            self._cap = None
