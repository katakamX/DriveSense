"""Eye- and mouth-aspect-ratio geometry over MediaPipe's 468-point topology.

Pure functions over landmark arrays: no MediaPipe, no OpenCV, no clock, no
socket. That is what makes the thresholds testable against synthetic points
rather than against a webcam and a volunteer willing to yawn on cue.

## On the duplication with `cv/drowsiness.py`

`eye_aspect_ratio` here computes the same quantity as `cv.drowsiness.
eye_aspect_ratio`, and that is a real duplication rather than an oversight.
The two run in different processes with different install sets: the `cv`
package is not a dependency of the backend, and making it one would invert
the direction ADR 0002 establishes (the CV process talks to the backend over
HTTP; the backend does not import it) and would drag MediaPipe into every
environment that installs `drivesense-backend`.

ADR 0004's "one implementation" rule is about *features the model consumes*,
where a divergence between training and serving silently corrupts a
prediction. Nothing here feeds the model. If the two ever need to agree on a
number, the fix is to lift this module into `contracts/`, not to have one
package import the other.

The mouth ratio has no counterpart in `cv/` at all — that process does not do
yawn detection.
"""

from __future__ import annotations

import numpy as np
import numpy.typing as npt

Points = npt.NDArray[np.float64]

# Six-point eye contours, ordered (corner, upper-1, upper-2, corner, lower-2,
# lower-1) so the same index math applies to both eyes. Eyelid contour rather
# than iris — the widely used mapping for EAR over FaceMesh landmarks, and the
# same indices `cv/landmarks.py` uses.
LEFT_EYE_INDICES = (362, 385, 387, 263, 373, 380)
RIGHT_EYE_INDICES = (33, 160, 158, 133, 153, 144)

# Inner-lip contour in the same six-point order, so `_aspect_ratio` below can
# treat a mouth exactly as it treats an eye. Inner lip, not outer: the outer
# contour moves when the lips purse or the jaw shifts without the mouth
# actually opening, which is precisely the false positive yawn detection has
# to avoid.
MOUTH_INDICES = (78, 81, 311, 308, 402, 178)


def _aspect_ratio(points: Points) -> float:
    """Mean vertical opening over horizontal width, for a six-point contour.

    `points` is `(6, 2)` in pixel coordinates, ordered (corner, upper-1,
    upper-2, corner, lower-2, lower-1).

    Returns 0.0 for a degenerate contour — a zero-width horizontal span means
    the landmarks are collapsed (a profile view, a detection artefact), and a
    ratio computed from it would be an infinity dressed up as a measurement.
    """
    p1, p2, p3, p4, p5, p6 = points
    vertical = float(np.linalg.norm(p2 - p6) + np.linalg.norm(p3 - p5))
    horizontal = float(np.linalg.norm(p1 - p4))
    if horizontal == 0.0:
        return 0.0
    return vertical / (2.0 * horizontal)


def eye_aspect_ratio(eye_points: Points) -> float:
    """Standard six-point EAR (Soukupová & Čech, 2016).

    Falls with the eyelid: ~0.3 for an open eye, near 0 for a closed one. The
    absolute value is person- and camera-specific — see `SESSION_EAR_CAVEAT`
    in `detector.py` for what that means for a fixed threshold.
    """
    return _aspect_ratio(eye_points)


def mouth_aspect_ratio(mouth_points: Points) -> float:
    """MAR over the inner lip, by direct analogy to EAR.

    Near 0 with the mouth closed, rising as the jaw drops. The same formula is
    doing the same job on a different contour; there is no separate literature
    formulation being invoked here beyond the analogy itself.
    """
    return _aspect_ratio(mouth_points)


def mean_eye_aspect_ratio(left_eye: Points, right_eye: Points) -> float:
    """EAR averaged across both eyes.

    Averaging rather than taking a minimum: one eye partially occluded by head
    rotation should pull the number down proportionally, not dictate it.
    """
    return (eye_aspect_ratio(left_eye) + eye_aspect_ratio(right_eye)) / 2.0
