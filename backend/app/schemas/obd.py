"""Wire shape for an OBD CSV replay: the whole file, chunked, in one response.

Synchronous by design — see `app.api.v1.obd`. Each chunk's `risk` field reuses
`RiskOut`, the exact shape the live WebSocket already publishes, so the
frontend's existing risk-band UI (`Badge`, `Trace`) needs no OBD-specific
branch to render it.
"""

from pydantic import BaseModel

from app.schemas.risk import RiskOut


class ObdChunkOut(BaseModel):
    """One playback step. `risk` is `None` until enough of the recording has
    played to compute a trailing-window assessment — see
    `app.core.obd.features.build_replay`."""

    t: float
    speed_kmh: float
    rpm: float
    gear: int
    throttle_pct: float
    brake_pct: float
    risk: RiskOut | None


class ObdAnalysisOut(BaseModel):
    row_count: int
    duration_s: float
    chunk_interval_s: float
    chunks: list[ObdChunkOut]
