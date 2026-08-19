"""Telemetry sinks.

`JsonlSink` writes one frame per line plus a metadata sidecar. `HttpSink`
publishes to the backend's ingest endpoint. Producers only ever see the
`TelemetrySink` protocol, so which one is attached is a caller's choice.
"""

from __future__ import annotations

import json
import logging
import time
from io import TextIOWrapper
from pathlib import Path
from types import TracebackType

import httpx

from drivesense_contracts import TelemetryFrame, TripMeta

logger = logging.getLogger(__name__)

DEFAULT_RECORDING_DIR = Path("data/recordings")

# Frames per POST. The backend's ingest endpoint takes a batch and runs event
# detection across it, so this is the granularity at which the whole ingest
# path is exercised. Ten is one second of telemetry at the simulator's default
# 10 Hz, matching the ~1 Hz batched-write rate docs/architecture.md designs for.
DEFAULT_BATCH_SIZE = 10

# Longest error-response body written to the log, same cap and same reason as
# `cv/client.py`: FastAPI's own error payloads are well under this, but an
# error page from whatever sits in front of the backend can be arbitrarily long.
MAX_LOGGED_BODY_CHARS = 500


class NullSink:
    """Discards frames. Used when recording is off."""

    def open(self, meta: TripMeta) -> None:
        return None

    def write(self, frame: TelemetryFrame) -> None:
        return None

    def close(self) -> None:
        return None


class MemorySink:
    """Collects frames in memory. Used by tests."""

    def __init__(self) -> None:
        self.meta: TripMeta | None = None
        self.frames: list[TelemetryFrame] = []
        self.closed = False

    def open(self, meta: TripMeta) -> None:
        self.meta = meta
        self.frames.clear()
        self.closed = False

    def write(self, frame: TelemetryFrame) -> None:
        self.frames.append(frame)

    def close(self) -> None:
        self.closed = True


class JsonlSink:
    """Newline-delimited JSON, one `TelemetryFrame` per line.

    The `.meta.json` sidecar records what produced the file. Without it a
    recording cannot be reproduced or trusted later, which matters directly
    for the ML milestones.
    """

    def __init__(self, directory: Path | str = DEFAULT_RECORDING_DIR) -> None:
        self.directory = Path(directory)
        self._handle: TextIOWrapper | None = None
        self.path: Path | None = None
        self.meta_path: Path | None = None
        self.frames_written = 0

    def open(self, meta: TripMeta) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        self.path = self.directory / f"{meta.trip_id}.jsonl"
        self.meta_path = self.directory / f"{meta.trip_id}.meta.json"

        self.meta_path.write_text(
            json.dumps(json.loads(meta.model_dump_json()), indent=2) + "\n",
            encoding="utf-8",
        )
        self._handle = self.path.open("w", encoding="utf-8", newline="\n")
        self.frames_written = 0

    def write(self, frame: TelemetryFrame) -> None:
        if self._handle is None:
            raise RuntimeError("JsonlSink.write called before open()")
        self._handle.write(frame.model_dump_json() + "\n")
        self.frames_written += 1

    def close(self) -> None:
        if self._handle is not None:
            self._handle.flush()
            self._handle.close()
            self._handle = None


class HttpSink:
    """Batched POST to `/api/v1/trips/{trip_id}/telemetry/batch`.

    ## Two different trip ids

    `TripMeta.trip_id` identifies a *recording* and is a producer-chosen string
    ("high_risk-b-seed007"). The backend's trip id is a UUID naming a row that
    already exists, created by staff against `POST /trips` with a driver and a
    vehicle. They are not interchangeable and the sink cannot derive one from
    the other, so the backend id is passed in explicitly at construction and
    `open()`'s metadata is used only for logging.

    ## Failures are counted, not raised and not hidden

    `cv/client.py` swallows send failures because CV is optional and a dead
    backend must not stop the analysis loop. The reasoning does not carry over:
    this sink feeds the M14 benchmark, and a run that silently dropped frames
    would report a throughput number for traffic that never arrived. Raising is
    no better — one blip would end a long run. So failures are logged and
    counted, and `frames_failed` is part of what a benchmark reports.

    ## `sent_at`

    `TelemetryFrame.ts` is simulated time (see the contract's docstring) and a
    headless run can produce it far faster or slower than a real clock would,
    so it cannot stand in for a send timestamp. For a benchmark to measure
    ingest-to-browser latency it needs to know when a frame actually left the
    process; `sent_at` records that, in wall-clock seconds, keyed by
    `frame.seq` (the producer's monotonic per-trip counter, and the same key
    the backend echoes back on the WebSocket telemetry message). All frames in
    a batch share one timestamp, taken immediately before the POST -- the
    batch is one network round trip, and that call is what the latency number
    is meant to capture.
    """

    def __init__(
        self,
        base_url: str,
        trip_id: str,
        *,
        batch_size: int = DEFAULT_BATCH_SIZE,
        timeout_s: float = 10.0,
        client: httpx.Client | None = None,
    ) -> None:
        if batch_size < 1:
            raise ValueError("batch_size must be at least 1")
        self.trip_id = trip_id
        self.batch_size = batch_size
        self._owns_client = client is None
        self._client = client or httpx.Client(base_url=base_url, timeout=timeout_s)
        self._path = f"/api/v1/trips/{trip_id}/telemetry/batch"
        self._pending: list[TelemetryFrame] = []
        self.frames_sent = 0
        self.frames_failed = 0
        self.batches_sent = 0
        self.batches_failed = 0
        self.sent_at: dict[int, float] = {}

    def open(self, meta: TripMeta) -> None:
        self._pending.clear()
        self.frames_sent = 0
        self.frames_failed = 0
        self.batches_sent = 0
        self.batches_failed = 0
        self.sent_at.clear()
        logger.info(
            "Posting recording %s to backend trip %s at %.0f Hz",
            meta.trip_id,
            self.trip_id,
            meta.sample_rate_hz,
        )

    def write(self, frame: TelemetryFrame) -> None:
        self._pending.append(frame)
        if len(self._pending) >= self.batch_size:
            self.flush()

    def flush(self) -> None:
        """POST whatever is buffered. A no-op when nothing is pending.

        The endpoint rejects an empty `frames` list (`min_length=1`), so the
        guard is required rather than merely an optimisation.
        """
        if not self._pending:
            return
        batch, self._pending = self._pending, []
        payload = {"frames": [frame.model_dump(mode="json") for frame in batch]}
        sent_wall_time = time.time()
        try:
            response = self._client.post(self._path, json=payload)
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            self._note_failure(len(batch), f"HTTP {exc.response.status_code}: {exc.response.text}")
        except httpx.HTTPError as exc:
            # Transport-level failure (connection refused, timeout, DNS): there
            # is no response whose body could say more than the exception does.
            self._note_failure(len(batch), str(exc))
        else:
            self.frames_sent += len(batch)
            self.batches_sent += 1
            for frame in batch:
                self.sent_at[frame.seq] = sent_wall_time

    def _note_failure(self, frame_count: int, detail: str) -> None:
        self.frames_failed += frame_count
        self.batches_failed += 1
        detail = detail.strip()
        if len(detail) > MAX_LOGGED_BODY_CHARS:
            detail = f"{detail[:MAX_LOGGED_BODY_CHARS]}... ({len(detail)} chars total)"
        logger.warning("Failed to POST %d telemetry frame(s): %s", frame_count, detail)

    def close(self) -> None:
        self.flush()
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> HttpSink:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()


def read_jsonl(path: Path | str) -> list[TelemetryFrame]:
    """Load a recording back into validated frames."""
    return [
        TelemetryFrame.model_validate_json(line)
        for line in Path(path).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
