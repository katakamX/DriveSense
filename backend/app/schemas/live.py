"""WebSocket message envelope for the live trip stream."""

from typing import Any, Literal

from pydantic import BaseModel


class LiveMessage(BaseModel):
    # `risk` arrives at 1 Hz from the inference tick, against `telemetry`'s
    # 10 Hz — see the frequency budget in docs/architecture.md. A client that
    # only knows the first two message types keeps working; it just never
    # sees the third.
    type: Literal["telemetry", "event", "risk"]
    data: dict[str, Any]
