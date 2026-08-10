"""WebSocket message envelope for the live trip stream."""

from typing import Any, Literal

from pydantic import BaseModel


class LiveMessage(BaseModel):
    type: Literal["telemetry", "event"]
    data: dict[str, Any]
