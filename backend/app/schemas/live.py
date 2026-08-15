"""WebSocket message envelope for the live trip stream."""

from typing import Any, Literal

from pydantic import BaseModel


class LiveMessage(BaseModel):
    # `risk` arrives at 1 Hz from the inference tick, against `telemetry`'s
    # 10 Hz — see the frequency budget in docs/architecture.md. A client that
    # only knows the first two message types keeps working; it just never
    # sees the third. `driver_state` also arrives at 1 Hz, pushed by the
    # separate CV process (ADR 0002) rather than the inference tick, and is
    # absent entirely whenever that process isn't running.
    #
    # The last two are connection-scoped rather than pipeline-scoped, which is
    # why they are published by the WebSocket route and never by `publish`:
    #
    # - `snapshot` — sent once, immediately after accept, so a client that
    #   connects between pushes is not staring at an empty page until the next
    #   one. See `app.core.live.snapshot`.
    # - `ping` — a server-side heartbeat every `live.PING_INTERVAL_S`. Its
    #   purpose is not liveness on the server's side but the client's: without
    #   traffic on an idle trip, a half-open connection is indistinguishable
    #   from a quiet one, and the browser goes on showing stale numbers under a
    #   "Live" label.
    type: Literal["telemetry", "event", "risk", "driver_state", "snapshot", "ping"]
    data: dict[str, Any]
