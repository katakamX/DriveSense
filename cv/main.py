"""Process entrypoint: capture -> landmarks -> drowsiness -> client (ADR 0002).

Two independently paced loops in one process:
  - Frame analysis runs at `--fps` (target 10-15 FPS, this milestone's exit
    criterion).
  - Reporting to the backend happens at 1 Hz, gated on a wall-clock timer
    rather than on frame count, so analysis FPS and report rate stay
    decoupled exactly as ADR 0002 describes.

Run from inside `cv/`: `python main.py --trip-id <uuid> --backend-url http://localhost:8000`
Add `--debug-window` during manual testing for a live preview of the feed
with the tracked eye landmarks drawn on it.
"""

from __future__ import annotations

import argparse
import contextlib
import logging
import sys
import time
import uuid
from datetime import UTC, datetime

import cv2
import numpy as np
import numpy.typing as npt

from capture import Camera
from client import DriverStateClient
from contracts import SCHEMA_VERSION, DriverStateFrame
from drowsiness import Calibration, DrowsinessAggregator, eye_aspect_ratio
from landmarks import FaceLandmarker, FaceLandmarksResult

logger = logging.getLogger(__name__)

REPORT_INTERVAL_S = 1.0

# How often the loop logs a one-line liveness summary. Frequent enough to
# watch calibration fill up in real time, sparse enough not to bury the
# POST failures that were previously the only output.
STATUS_INTERVAL_S = 2.0

DEBUG_WINDOW_NAME = "DriveSense (q or ESC to quit)"


def _mean_ear(left_eye: npt.NDArray[np.float64], right_eye: npt.NDArray[np.float64]) -> float:
    return (eye_aspect_ratio(left_eye) + eye_aspect_ratio(right_eye)) / 2.0


def _calibration_status(calibration: Calibration) -> str:
    if calibration.is_calibrated:
        return f"calibration complete (baseline EAR={calibration.baseline_ear:.3f})"
    return f"calibrating: {calibration.sample_count}/{calibration.target_samples} frames"


def _draw_overlay(
    frame: npt.NDArray[np.uint8],
    result: FaceLandmarksResult,
    ear: float | None,
    calibration: Calibration,
    aggregator: DrowsinessAggregator,
) -> None:
    """Draw the tracked eye contours and a status readout onto `frame` in place.

    Only the two eye contours are drawn because those are the only landmarks
    `FaceLandmarker` extracts (see `landmarks.py`) — and they are the exact
    points EAR is computed from, so a wrong-looking contour here explains a
    wrong-looking EAR directly.
    """
    colour = (0, 255, 0) if result.face_detected else (0, 0, 255)

    if result.face_detected:
        assert result.left_eye is not None and result.right_eye is not None
        for eye in (result.left_eye, result.right_eye):
            points = eye.astype(np.int32)
            cv2.polylines(frame, [points], isClosed=True, color=colour, thickness=1)
            for x, y in points.tolist():
                cv2.circle(frame, (int(x), int(y)), 2, colour, -1)

    lines = [
        f"face: {'yes' if result.face_detected else 'NO'}",
        f"EAR: {ear:.3f}" if ear is not None else "EAR: --",
        _calibration_status(calibration),
    ]
    if calibration.is_calibrated:
        perclos = aggregator.perclos
        blink_rate = aggregator.blink_rate_per_min
        lines.append(
            f"PERCLOS: {perclos:.2f}" if perclos is not None else "PERCLOS: --",
        )
        lines.append(
            f"blinks: {blink_rate:.1f}/min" if blink_rate is not None else "blinks: --",
        )

    for i, line in enumerate(lines):
        origin = (10, 30 + i * 26)
        # Black outline first, then the text itself, so the readout stays
        # legible against both a dark and a bright scene.
        cv2.putText(frame, line, origin, cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 0), 4)
        cv2.putText(frame, line, origin, cv2.FONT_HERSHEY_SIMPLEX, 0.7, colour, 1)


def run(
    trip_id: str,
    backend_url: str,
    device_index: int = 0,
    target_fps: float = 15.0,
    calibration_samples: int = 30,
    debug_window: bool = False,
) -> None:
    camera = Camera(device_index=device_index)
    landmarker = FaceLandmarker()
    calibration = Calibration(target_samples=calibration_samples)
    aggregator = DrowsinessAggregator()
    client = DriverStateClient(base_url=backend_url)

    frame_count = 0
    loop_start = time.monotonic()
    last_report = 0.0

    # Per-status-interval counters, reset on every status log.
    last_status = loop_start
    frames_since_status = 0
    faces_since_status = 0

    logger.info(
        "Starting CV monitoring for trip %s (calibrating on first %d open-eye frames)",
        trip_id,
        calibration_samples,
    )

    try:
        for frame in camera.frames(target_fps=target_fps):
            frame_count += 1
            now_s = time.monotonic()
            if frame_count == 1:
                # Camera open and model warm-up land between `loop_start` and
                # the first frame; start the FPS window here so the first
                # status line reports the loop's rate, not the startup cost.
                last_status = now_s
            frames_since_status += 1
            result = landmarker.process(frame)
            faces_since_status += int(result.face_detected)

            ear = None
            if result.face_detected:
                assert result.left_eye is not None and result.right_eye is not None
                ear = _mean_ear(result.left_eye, result.right_eye)
                if not calibration.is_calibrated:
                    calibration.add_sample(ear)
                    if calibration.is_calibrated:
                        logger.info(
                            "Calibration complete: baseline EAR=%.3f, closed threshold=%.3f",
                            calibration.baseline_ear,
                            calibration.closed_threshold,
                        )
                else:
                    aggregator.add_sample(now_s, ear, calibration.closed_threshold)

            if now_s - last_report >= REPORT_INTERVAL_S:
                last_report = now_s
                state_frame = DriverStateFrame(
                    schema_version=SCHEMA_VERSION,
                    trip_id=trip_id,
                    ts=datetime.now(UTC),
                    face_detected=result.face_detected,
                    calibrated=calibration.is_calibrated,
                    drowsiness=aggregator.perclos if calibration.is_calibrated else None,
                    perclos=aggregator.perclos if calibration.is_calibrated else None,
                    blink_rate_per_min=(
                        aggregator.blink_rate_per_min if calibration.is_calibrated else None
                    ),
                )
                client.submit(state_frame)

            if now_s - last_status >= STATUS_INTERVAL_S:
                interval_s = now_s - last_status
                logger.info(
                    "face detected in %d/%d frames | %s | %.1f FPS",
                    faces_since_status,
                    frames_since_status,
                    _calibration_status(calibration),
                    frames_since_status / interval_s if interval_s > 0 else 0.0,
                )
                last_status = now_s
                frames_since_status = 0
                faces_since_status = 0

            if debug_window:
                _draw_overlay(frame, result, ear, calibration, aggregator)
                try:
                    cv2.imshow(DEBUG_WINDOW_NAME, frame)
                    key = cv2.waitKey(1) & 0xFF
                    # The window's X button produces no key event, so check
                    # visibility too rather than running on against a window
                    # that is no longer on screen.
                    dismissed = cv2.getWindowProperty(DEBUG_WINDOW_NAME, cv2.WND_PROP_VISIBLE) < 1
                except cv2.error:
                    # Headless OpenCV build (opencv-python-headless) has no GUI
                    # support; say so once and keep the pipeline running.
                    logger.exception(
                        "Cannot open the debug window — this OpenCV build has no GUI "
                        "support. Continuing without it."
                    )
                    debug_window = False
                    continue
                if key in (ord("q"), 27) or dismissed:
                    logger.info("Debug window closed; stopping capture")
                    break

        elapsed = time.monotonic() - loop_start
        achieved_fps = frame_count / elapsed if elapsed > 0 else 0.0
        logger.info(
            "Capture loop ended after %d frames in %.1fs (%.1f FPS)",
            frame_count,
            elapsed,
            achieved_fps,
        )
    finally:
        camera.release()
        landmarker.close()
        client.close()
        if debug_window:
            # No window exists if the build is headless or it was never shown.
            with contextlib.suppress(cv2.error):
                cv2.destroyWindow(DEBUG_WINDOW_NAME)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-8s %(message)s")
    parser = argparse.ArgumentParser(description="DriveSense CV driver-monitoring process")
    parser.add_argument("--trip-id", required=True)
    parser.add_argument("--backend-url", default="http://localhost:8000")
    parser.add_argument("--device-index", type=int, default=0)
    parser.add_argument("--fps", type=float, default=15.0)
    parser.add_argument("--calibration-samples", type=int, default=30)
    parser.add_argument(
        "--debug-window",
        action="store_true",
        help="show a live preview window with the tracked eye landmarks drawn (manual testing)",
    )
    args = parser.parse_args()

    # Fail here rather than at the first POST. The ingest endpoint parses
    # `trip_id` out of the body itself and rejects a non-UUID with 422, so an
    # id that is merely the wrong shape produces no camera-side symptom at
    # all: capture and calibration run normally while every report is
    # rejected, once a second, for as long as the process lives.
    try:
        uuid.UUID(args.trip_id)
    except ValueError:
        parser.error(
            f"--trip-id must be a trip UUID, got {args.trip_id!r}. "
            "Create a trip with POST /api/v1/trips (or take an existing id "
            "from GET /api/v1/trips) and pass the `id` it returns."
        )

    try:
        run(
            trip_id=args.trip_id,
            backend_url=args.backend_url,
            device_index=args.device_index,
            target_fps=args.fps,
            calibration_samples=args.calibration_samples,
            debug_window=args.debug_window,
        )
    except KeyboardInterrupt:
        logger.info("Interrupted, shutting down")
        sys.exit(0)


if __name__ == "__main__":
    main()
