"""Online windowing: the bounded per-trip buffer and the 1 Hz inference tick.

`buffer` turns a stream of HTTP batches back into a trailing 30-second window;
`ticker` reduces that window to features on its own clock and runs the model
over it. Together they are the M4 ring buffer the offline pipeline never
needed and the M9 risk engine cannot work without.
"""

from app.core.windowing.buffer import (
    MAX_SAMPLES,
    WINDOW_SPAN_S,
    append,
    buffered_count,
    snapshot,
)
from app.core.windowing.buffer import discard_trip as discard_buffer
from app.core.windowing.buffer import tracked_trip_count as buffered_trip_count
from app.core.windowing.ticker import (
    TICK_INTERVAL_S,
    TripInference,
    ensure_started,
    latest_inference,
    running_trip_count,
    stop_all,
    stop_trip,
)

__all__ = [
    "MAX_SAMPLES",
    "TICK_INTERVAL_S",
    "WINDOW_SPAN_S",
    "TripInference",
    "append",
    "buffered_count",
    "buffered_trip_count",
    "discard_buffer",
    "ensure_started",
    "latest_inference",
    "running_trip_count",
    "snapshot",
    "stop_all",
    "stop_trip",
]
