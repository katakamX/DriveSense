"""Colour palette, mirroring frontend/src/styles/tokens.css.

The simulator and the dashboard should read as one product. These values are
copied deliberately rather than imported — the frontend owns its tokens, and
duplicating six hex strings is cheaper than coupling a Python package to a CSS
file.
"""

from __future__ import annotations

RGB = tuple[int, int, int]


def _hex(value: str) -> RGB:
    return (int(value[1:3], 16), int(value[3:5], 16), int(value[5:7], 16))


SURFACE_BASE: RGB = _hex("#08090c")
SURFACE_RAISED: RGB = _hex("#0f1116")
SURFACE_OVERLAY: RGB = _hex("#161922")
BORDER_SUBTLE: RGB = _hex("#1e222c")
BORDER_STRONG: RGB = _hex("#2b3040")

CONTENT_PRIMARY: RGB = _hex("#e8eaf0")
CONTENT_SECONDARY: RGB = _hex("#9aa1b1")
CONTENT_MUTED: RGB = _hex("#5f6675")

ACCENT: RGB = _hex("#22d3ee")
ACCENT_MUTED: RGB = _hex("#0e7490")

RISK_LOW: RGB = _hex("#34d399")
RISK_MODERATE: RGB = _hex("#fbbf24")
RISK_HIGH: RGB = _hex("#fb923c")
RISK_CRITICAL: RGB = _hex("#f43f5e")

ROAD: RGB = (26, 28, 34)
ROAD_EDGE: RGB = (58, 63, 76)
LANE_MARK: RGB = (150, 156, 170)
SKY: RGB = (13, 16, 22)
GROUND: RGB = (16, 20, 26)


def lerp(a: RGB, b: RGB, t: float) -> RGB:
    t = max(0.0, min(1.0, t))
    return (
        int(a[0] + (b[0] - a[0]) * t),
        int(a[1] + (b[1] - a[1]) * t),
        int(a[2] + (b[2] - a[2]) * t),
    )
