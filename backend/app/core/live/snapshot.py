"""What a client is told the moment it connects, before the stream resumes.

Every other message on the live socket is a *push*: something happened, and
subscribers are told. That works until the client arrives between pushes — on
a first page load mid-trip, or on the reconnect after a backend restart — at
which point it holds nothing and the page shows dashes until the pipeline
happens to produce something. On an idle trip that can be a while, and the
difference between "no data yet" and "broken" is not visible from the browser.

So the socket opens with one `snapshot` message carrying the three things the
Live Drive page renders: the most recent telemetry frame, the most recent risk
assessment, and the trip's recent driving events.

## Two of the three are memory, and that is the honest answer

`telemetry` and `risk` come from the in-process buffer and the tick's last
output. Both are empty immediately after a restart, and this module does not
try to hide that by reading the last telemetry row back out of the database:
the ring buffer is the live path's state (ADR 0001), a restart loses it, and
the snapshot's job is to report what the server currently knows rather than to
reconstruct an appearance of continuity it does not have. The client keeps
showing its own last-known values across a reconnect; that is where continuity
lives, and it does not require the server to pretend.

`events` is the exception because driving events are *written* before they are
published, so the table is not a reconstruction — it is the same list, already
complete, and a client that reconnects gets back the events it missed rather
than a hole.

## Not exported from `app.core.live`

`app.core.live.__init__` imports the broadcaster only. This module reaches into
`app.core.windowing`, whose package init imports the ticker, which imports
`publish` from `app.core.live` — re-exporting this module from that init would
close the cycle. It is imported directly by the WebSocket route instead, which
is the only caller it has.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.windowing import buffer, ticker
from app.db.models import DrivingEvent
from app.schemas.risk import RiskOut

# Matches the client's `MAX_EVENTS`. A snapshot that returned more would be
# trimmed on arrival; one that returned fewer would leave a reconnecting client
# with a shorter history than it had before the drop.
RECENT_EVENT_LIMIT = 20


async def build_snapshot(session: AsyncSession, trip_id: uuid.UUID) -> dict[str, Any]:
    """Assemble the connect-time payload for one trip.

    Every key is always present; each is independently nullable or empty, so a
    client reads three optional facts rather than having to branch on whether
    it got a snapshot at all.
    """
    return {
        "telemetry": _latest_telemetry(trip_id),
        "risk": _latest_risk(trip_id),
        "events": await _recent_events(session, trip_id),
    }


def _latest_telemetry(trip_id: uuid.UUID) -> dict[str, Any] | None:
    """The newest buffered frame, shaped exactly like a `telemetry` message.

    Shaped identically on purpose: the client applies it through the same code
    path as a pushed frame, so there is no second definition of what a frame
    looks like to drift out of step with the first.
    """
    samples = buffer.snapshot(trip_id)
    if not samples:
        return None
    newest = samples[-1]
    return {
        "recorded_at": newest.recorded_at.isoformat(),
        "speed_kph": newest.speed_kph,
        "accel_ms2": newest.accel_ms2,
        "lateral_accel_ms2": newest.lateral_accel_ms2,
        "lat": newest.lat,
        "lon": newest.lon,
    }


def _latest_risk(trip_id: uuid.UUID) -> dict[str, Any] | None:
    inference = ticker.latest_inference(trip_id)
    if inference is None:
        return None
    return RiskOut.from_assessment(inference.risk).model_dump(mode="json")


async def _recent_events(session: AsyncSession, trip_id: uuid.UUID) -> list[dict[str, Any]]:
    """The trip's most recent events, newest first — the client's display order."""
    result = await session.execute(
        select(DrivingEvent)
        .where(DrivingEvent.trip_id == trip_id)
        .order_by(DrivingEvent.occurred_at.desc())
        .limit(RECENT_EVENT_LIMIT)
    )
    return [
        {
            "event_type": row.event_type,
            "occurred_at": row.occurred_at.isoformat(),
            "measured_value": row.measured_value,
            "threshold_value": row.threshold_value,
        }
        for row in result.scalars().all()
    ]


__all__ = ["RECENT_EVENT_LIMIT", "build_snapshot"]
