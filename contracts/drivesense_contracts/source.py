"""Producer-side telemetry abstractions.

These protocols live on the **producer** side of the wire. A producer process
(the simulator today, an OBD2/ELM327 adapter later) owns a `TelemetrySource`
and pumps its frames into one or more `TelemetrySink`s.

The backend does **not** import or depend on `TelemetrySource`. It receives
frames over the network and knows nothing about how they were produced — see
docs/adr/0001-stream-oriented-backend.md and
docs/adr/0005-shared-contracts-package.md.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Protocol, runtime_checkable

from drivesense_contracts.telemetry import TelemetryFrame, TripMeta


@runtime_checkable
class TelemetrySource(Protocol):
    """Something that produces telemetry frames for a single trip."""

    @property
    def source_name(self) -> str:
        """Stable identifier for the producer, e.g. "simulator"."""
        ...

    def start(self, trip_id: str) -> TripMeta:
        """Begin a trip and return the metadata describing this run."""
        ...

    def frames(self) -> Iterator[TelemetryFrame]:
        """Yield frames until the source is exhausted or stopped."""
        ...

    def stop(self) -> None:
        """Release any resources held by the source."""
        ...


@runtime_checkable
class TelemetrySink(Protocol):
    """Somewhere frames go: a file today, the backend API from Milestone 4."""

    def open(self, meta: TripMeta) -> None: ...

    def write(self, frame: TelemetryFrame) -> None: ...

    def close(self) -> None: ...
