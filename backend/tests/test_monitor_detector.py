"""Sustained-condition logic and frame decoding for the driver monitor.

The landmark extractor is faked throughout. MediaPipe's output on a real face
is not the thing under test here — the state machine that turns a stream of
ratios into an alert is, and it is testable only if the timeline and the
landmarks are both under the test's control.
"""

from __future__ import annotations

import base64
import math

import cv2
import numpy as np
import numpy.typing as npt
import pytest

from app.core.monitor import (
    FrameDecodeError,
    MonitorSession,
    decode_frame,
    eye_aspect_ratio,
    mouth_aspect_ratio,
)
from app.core.monitor.landmarker import FaceLandmarks

# A frame the fake extractor never looks at. `observe` passes it straight
# through to the extractor, so its content is irrelevant to these tests.
BLANK = np.zeros((8, 8, 3), dtype=np.uint8)


def contour(vertical: float, horizontal: float = 10.0) -> npt.NDArray[np.float64]:
    """Six points whose aspect ratio is exactly `vertical / horizontal`.

    Both vertical pairs are set to the same separation, so the mean the ratio
    takes is that separation and the expected value is readable off the call.
    """
    return np.array(
        [
            (0.0, 0.0),  # p1 — left corner
            (3.0, vertical / 2.0),  # p2 — upper-left
            (7.0, vertical / 2.0),  # p3 — upper-right
            (horizontal, 0.0),  # p4 — right corner
            (7.0, -vertical / 2.0),  # p5 — lower-right
            (3.0, -vertical / 2.0),  # p6 — lower-left
        ],
        dtype=np.float64,
    )


class FakeExtractor:
    """Returns whatever landmarks the test queues up, one per `process` call."""

    def __init__(self, results: list[FaceLandmarks]) -> None:
        self._results = list(results)
        self.closed = False

    def process(self, frame_bgr: npt.NDArray[np.uint8]) -> FaceLandmarks:
        return self._results.pop(0) if self._results else FaceLandmarks(face_detected=False)

    def close(self) -> None:
        self.closed = True


def face(*, ear: float, mar: float) -> FaceLandmarks:
    eye = contour(ear * 10.0)
    return FaceLandmarks(
        face_detected=True,
        left_eye=eye,
        right_eye=eye,
        mouth=contour(mar * 10.0),
    )


NO_FACE = FaceLandmarks(face_detected=False)


def session(results: list[FaceLandmarks]) -> MonitorSession:
    return MonitorSession(extractor=FakeExtractor(results))  # type: ignore[arg-type]


# --- geometry ---------------------------------------------------------------


def test_aspect_ratio_matches_the_constructed_contour() -> None:
    assert eye_aspect_ratio(contour(2.0)) == pytest.approx(0.2)
    assert mouth_aspect_ratio(contour(7.0)) == pytest.approx(0.7)


def test_degenerate_contour_is_zero_not_infinite() -> None:
    """A collapsed horizontal span must not produce an infinity."""
    collapsed = np.zeros((6, 2), dtype=np.float64)
    collapsed[1] = (0.0, 5.0)
    assert eye_aspect_ratio(collapsed) == 0.0
    assert math.isfinite(eye_aspect_ratio(collapsed))


# --- drowsiness dwell -------------------------------------------------------


def test_closed_eyes_below_the_dwell_do_not_report_drowsy() -> None:
    monitor = session([face(ear=0.10, mar=0.1)] * 2)
    assert monitor.observe(BLANK, 0.0).eyes_closed is True
    assert monitor.observe(BLANK, 1.4).drowsy is False


def test_closed_eyes_sustained_past_the_dwell_report_drowsy() -> None:
    monitor = session([face(ear=0.10, mar=0.1)] * 2)
    monitor.observe(BLANK, 0.0)
    assert monitor.observe(BLANK, 1.5).drowsy is True


def test_a_blink_resets_the_dwell() -> None:
    """Closed, open, closed must not accumulate across the gap."""
    monitor = session([face(ear=0.10, mar=0.1), face(ear=0.30, mar=0.1), face(ear=0.10, mar=0.1)])
    monitor.observe(BLANK, 0.0)
    assert monitor.observe(BLANK, 1.0).drowsy is False
    # 1.4 s after this frame is 2.4 s after the first — past the dwell if the
    # clock had kept running through the open frame.
    assert monitor.observe(BLANK, 2.4).drowsy is False


def test_ear_at_the_threshold_is_open() -> None:
    """The comparison is strict, so a driver sitting exactly at 0.21 is not drowsy."""
    monitor = session([face(ear=0.21, mar=0.1)] * 2)
    monitor.observe(BLANK, 0.0)
    assert monitor.observe(BLANK, 5.0).eyes_closed is False


# --- yawning ----------------------------------------------------------------


def test_open_mouth_sustained_past_the_dwell_reports_yawning() -> None:
    monitor = session([face(ear=0.30, mar=0.8)] * 2)
    assert monitor.observe(BLANK, 0.0).yawning is False
    assert monitor.observe(BLANK, 1.0).yawning is True


def test_yawning_and_drowsy_are_independent() -> None:
    """A yawn with open eyes is a yawn, not drowsiness."""
    monitor = session([face(ear=0.30, mar=0.8)] * 2)
    monitor.observe(BLANK, 0.0)
    result = monitor.observe(BLANK, 1.0)
    assert result.yawning is True
    assert result.drowsy is False


# --- face absence -----------------------------------------------------------


def test_missing_face_reports_not_visible_only_after_the_dwell() -> None:
    monitor = session([NO_FACE] * 2)
    assert monitor.observe(BLANK, 0.0).not_visible is False
    assert monitor.observe(BLANK, 2.0).not_visible is True


def test_missing_face_reports_null_ratios_not_zero() -> None:
    """Zero would be indistinguishable from a shut eye. Missing is missing."""
    result = session([NO_FACE]).observe(BLANK, 0.0)
    assert result.ear is None
    assert result.mar is None
    assert result.face_detected is False


def test_face_leaving_frame_does_not_become_drowsiness() -> None:
    """Eyes-closed must not keep accumulating through an absence.

    Without the reset in `_observe_no_face`, a driver who closed their eyes
    for one frame and then turned away would be reported drowsy 1.5 s later,
    having never been observed with their eyes shut again.
    """
    monitor = session([face(ear=0.10, mar=0.1), NO_FACE, face(ear=0.10, mar=0.1)])
    monitor.observe(BLANK, 0.0)
    monitor.observe(BLANK, 0.2)
    assert monitor.observe(BLANK, 1.6).drowsy is False


def test_reappearing_face_clears_not_visible() -> None:
    monitor = session([NO_FACE, NO_FACE, face(ear=0.30, mar=0.1)])
    monitor.observe(BLANK, 0.0)
    assert monitor.observe(BLANK, 3.0).not_visible is True
    assert monitor.observe(BLANK, 3.2).not_visible is False


# --- frame decoding ---------------------------------------------------------


def jpeg_data_url() -> str:
    ok, encoded = cv2.imencode(".jpg", np.full((16, 16, 3), 127, dtype=np.uint8))
    assert ok
    return "data:image/jpeg;base64," + base64.b64encode(encoded.tobytes()).decode()


def test_decodes_a_browser_style_data_url() -> None:
    image = decode_frame(jpeg_data_url())
    assert image.shape == (16, 16, 3)


def test_decodes_a_bare_base64_payload() -> None:
    image = decode_frame(jpeg_data_url().split(",", 1)[1])
    assert image.shape == (16, 16, 3)


@pytest.mark.parametrize(
    "payload",
    ["data:image/jpeg;base64,not!valid!base64", "data:image/jpeg;base64,", "aGVsbG8="],
    ids=["not-base64", "empty", "base64-but-not-an-image"],
)
def test_undecodable_frames_raise_frame_decode_error(payload: str) -> None:
    with pytest.raises(FrameDecodeError):
        decode_frame(payload)
