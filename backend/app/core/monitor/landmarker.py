"""MediaPipe face-landmark extraction for the browser-camera monitor path.

## "Face Mesh" means the Tasks API here

MediaPipe's `mp.solutions.face_mesh` — the entry point most FaceMesh tutorials
use — was **removed in mediapipe 1.0**, which is the version this project
installs. `mediapipe.tasks.python.vision.FaceLandmarker` replaces it: same
underlying model, same 468-point topology, different Python surface. Code
written against `mp.solutions` will not import, so this module uses Tasks and
`cv/landmarks.py` already made the same move for the same reason.

## Image mode, not video mode

`cv/landmarks.py` runs the landmarker in `RunningMode.VIDEO`, which is right
for a process that owns a camera and sees every frame in order. This path does
not: frames arrive over a WebSocket from a browser that may drop, delay or
reorder them, and VIDEO mode's monotonic-timestamp contract would be a promise
this transport cannot keep. `RunningMode.IMAGE` treats each frame
independently, which is what the data actually is.

## The model bundle

Not shipped inside the pip package, so it is fetched once from Google's
documented URL and cached next to this module. Downloaded with `urllib` from
the standard library rather than `httpx`, to keep the backend's *runtime*
dependency set unchanged (`httpx` is a test-only dependency here).
"""

from __future__ import annotations

import logging
import threading
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import mediapipe as mp
import numpy as np
import numpy.typing as npt
from mediapipe.tasks.python import vision
from mediapipe.tasks.python.core.base_options import BaseOptions

from app.core.monitor.geometry import (
    LEFT_EYE_INDICES,
    MOUTH_INDICES,
    RIGHT_EYE_INDICES,
    Points,
)

logger = logging.getLogger(__name__)

MODEL_URL = (
    "https://storage.googleapis.com/mediapipe-models/face_landmarker/"
    "face_landmarker/float16/1/face_landmarker.task"
)
DEFAULT_MODEL_PATH = Path(__file__).parent / ".models" / "face_landmarker.task"

# One download at a time. Several WebSocket connections opening at once on a
# cold checkout would otherwise race to write the same file, and the loser
# would hand a truncated bundle to MediaPipe.
_download_lock = threading.Lock()


def ensure_model(model_path: Path = DEFAULT_MODEL_PATH) -> Path:
    """Download and cache the Face Landmarker bundle if it is not already local.

    Writes to a temporary path and renames, so an interrupted download leaves
    no half-written file that the next call would treat as cached.
    """
    if model_path.exists():
        return model_path
    with _download_lock:
        if model_path.exists():
            return model_path
        model_path.parent.mkdir(parents=True, exist_ok=True)
        logger.info("Downloading face landmarker model from %s", MODEL_URL)
        temp_path = model_path.with_suffix(".partial")
        with urllib.request.urlopen(MODEL_URL, timeout=60) as response:  # noqa: S310
            temp_path.write_bytes(response.read())
        temp_path.replace(model_path)
        logger.info("Model cached at %s", model_path)
    return model_path


@dataclass(frozen=True)
class FaceLandmarks:
    """The three contours this feature needs, in pixel coordinates.

    `face_detected` false means every contour is `None`. They are not optional
    independently: the model either fits a face or it does not.
    """

    face_detected: bool
    left_eye: Points | None = None
    right_eye: Points | None = None
    mouth: Points | None = None


class FaceLandmarkExtractor:
    """One MediaPipe landmarker. **Not thread-safe — one per session.**

    MediaPipe's landmarker holds native per-instance state and must not be
    called concurrently from two threads. Since every call is dispatched to a
    thread pool (see `app.api.v1.driver_monitor`), "one instance per WebSocket
    connection, used by one task at a time" is what keeps that true.
    """

    def __init__(
        self,
        model_path: Path | None = None,
        min_detection_confidence: float = 0.5,
    ) -> None:
        resolved = ensure_model(model_path or DEFAULT_MODEL_PATH)
        options = vision.FaceLandmarkerOptions(
            base_options=BaseOptions(model_asset_path=str(resolved)),
            running_mode=vision.RunningMode.IMAGE,
            num_faces=1,
            min_face_detection_confidence=min_detection_confidence,
        )
        self._landmarker = vision.FaceLandmarker.create_from_options(options)

    def process(self, frame_bgr: npt.NDArray[np.uint8]) -> FaceLandmarks:
        """Run the landmarker on one BGR frame and extract the eye/mouth contours."""
        height, width = frame_bgr.shape[:2]
        rgb = np.ascontiguousarray(frame_bgr[:, :, ::-1])  # the model expects RGB
        mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
        result = self._landmarker.detect(mp_image)

        if not result.face_landmarks:
            return FaceLandmarks(face_detected=False)

        landmarks = result.face_landmarks[0]
        return FaceLandmarks(
            face_detected=True,
            left_eye=_pixel_points(landmarks, LEFT_EYE_INDICES, width, height),
            right_eye=_pixel_points(landmarks, RIGHT_EYE_INDICES, width, height),
            mouth=_pixel_points(landmarks, MOUTH_INDICES, width, height),
        )

    def close(self) -> None:
        self._landmarker.close()


def _pixel_points(landmarks: Any, indices: tuple[int, ...], width: int, height: int) -> Points:
    # `landmarks` is mediapipe's `NormalizedLandmark` list; the package ships
    # no type stubs (see `[tool.mypy.overrides]`), so `Any` is already what
    # `result.face_landmarks[0]` is.
    return np.array(
        [(landmarks[i].x * width, landmarks[i].y * height) for i in indices],
        dtype=np.float64,
    )
