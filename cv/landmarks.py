"""MediaPipe Face Landmarker wrapper, extracting the eye landmarks EAR needs.

MediaPipe over Haar cascades per cv/README.md: cascades are fragile to head
rotation, lighting and glasses.

Uses MediaPipe's Tasks API (`mediapipe.tasks.python.vision.FaceLandmarker`) —
the package's older `mp.solutions.face_mesh` API (what cv/README.md's note
was originally written against) was removed in mediapipe 1.0; the installed
version here (1.0.0) only exposes Tasks. Same underlying model, same 468-point
topology, different Python entry point.

Only the two six-point eye contours used by the standard eye-aspect-ratio
formula are extracted here — the model produces 468 points per face, and
nothing downstream needs the rest.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import mediapipe as mp
import numpy as np
import numpy.typing as npt
from mediapipe.tasks.python import vision
from mediapipe.tasks.python.core.base_options import BaseOptions

logger = logging.getLogger(__name__)

# Six-point eye contours, ordered (corner, upper-1, upper-2, corner, lower-2,
# lower-1) so `drowsiness.eye_aspect_ratio` can apply the same index math to
# both eyes. These are the indices the model's 468-point topology assigns to
# the eyelid contour rather than the iris — a widely used mapping for
# EAR-from-FaceMesh landmarks.
LEFT_EYE_INDICES = (362, 385, 387, 263, 373, 380)
RIGHT_EYE_INDICES = (33, 160, 158, 133, 153, 144)

# Official Google-hosted asset for MediaPipe's Face Landmarker task, per
# https://ai.google.dev/edge/mediapipe/solutions/vision/face_landmarker —
# not shipped in the `mediapipe` pip package, so it is fetched once and
# cached locally on first run.
MODEL_URL = (
    "https://storage.googleapis.com/mediapipe-models/face_landmarker/"
    "face_landmarker/float16/1/face_landmarker.task"
)
DEFAULT_MODEL_PATH = Path(__file__).parent / ".models" / "face_landmarker.task"


def ensure_model(model_path: Path = DEFAULT_MODEL_PATH) -> Path:
    """Download the Face Landmarker model bundle if not already cached."""
    if model_path.exists():
        return model_path
    model_path.parent.mkdir(parents=True, exist_ok=True)
    logger.info("Downloading face landmarker model from %s", MODEL_URL)
    with httpx.stream("GET", MODEL_URL, follow_redirects=True, timeout=60.0) as response:
        response.raise_for_status()
        with open(model_path, "wb") as f:
            for chunk in response.iter_bytes():
                f.write(chunk)
    logger.info("Model cached at %s", model_path)
    return model_path


@dataclass(frozen=True)
class FaceLandmarksResult:
    face_detected: bool
    left_eye: npt.NDArray[np.float64] | None  # (6, 2) pixel coordinates
    right_eye: npt.NDArray[np.float64] | None  # (6, 2) pixel coordinates


class FaceLandmarker:
    """Thin wrapper around `mediapipe.tasks.python.vision.FaceLandmarker`."""

    def __init__(
        self,
        model_path: Path | None = None,
        num_faces: int = 1,
        min_detection_confidence: float = 0.5,
    ) -> None:
        resolved_path = ensure_model(model_path or DEFAULT_MODEL_PATH)
        options = vision.FaceLandmarkerOptions(
            base_options=BaseOptions(model_asset_path=str(resolved_path)),
            running_mode=vision.RunningMode.VIDEO,
            num_faces=num_faces,
            min_face_detection_confidence=min_detection_confidence,
        )
        self._landmarker = vision.FaceLandmarker.create_from_options(options)
        self._frame_index = 0

    def process(self, frame_bgr: npt.NDArray[np.uint8]) -> FaceLandmarksResult:
        """Run the landmarker on one BGR frame (as OpenCV yields) and extract eyes."""
        height, width = frame_bgr.shape[:2]
        rgb = np.ascontiguousarray(frame_bgr[:, :, ::-1])  # the model expects RGB
        mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)

        # VIDEO mode requires a monotonically increasing timestamp per frame,
        # not wall-clock time; a synthetic per-frame counter satisfies that
        # without coupling this class to the caller's clock.
        timestamp_ms = self._frame_index * 33
        self._frame_index += 1
        result = self._landmarker.detect_for_video(mp_image, timestamp_ms)

        if not result.face_landmarks:
            return FaceLandmarksResult(face_detected=False, left_eye=None, right_eye=None)

        landmarks = result.face_landmarks[0]
        left_eye = _pixel_points(landmarks, LEFT_EYE_INDICES, width, height)
        right_eye = _pixel_points(landmarks, RIGHT_EYE_INDICES, width, height)
        return FaceLandmarksResult(face_detected=True, left_eye=left_eye, right_eye=right_eye)

    def close(self) -> None:
        self._landmarker.close()


def _pixel_points(
    landmarks: Any, indices: tuple[int, ...], width: int, height: int
) -> npt.NDArray[np.float64]:
    # `landmarks` is `mediapipe`'s `NormalizedLandmark` list; the package
    # ships no type stubs (see `[tool.mypy.overrides]` for `mediapipe.*`),
    # so `Any` is what the caller's `result.face_landmarks[0]` already is.
    return np.array(
        [(landmarks[i].x * width, landmarks[i].y * height) for i in indices],
        dtype=np.float64,
    )
