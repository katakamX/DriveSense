"""Telemetry sinks.

`JsonlSink` writes one frame per line plus a metadata sidecar. From Milestone 4
an HTTP sink will publish to the backend; nothing else has to change, because
producers only ever see the `TelemetrySink` protocol.
"""

from __future__ import annotations

import json
from io import TextIOWrapper
from pathlib import Path

from drivesense_contracts import TelemetryFrame, TripMeta

DEFAULT_RECORDING_DIR = Path("data/recordings")


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


def read_jsonl(path: Path | str) -> list[TelemetryFrame]:
    """Load a recording back into validated frames."""
    return [
        TelemetryFrame.model_validate_json(line)
        for line in Path(path).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
