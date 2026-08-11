"""1 Hz POST of derived scalars to the backend (ADR 0002).

Only `DriverStateFrame` — never a raw frame — crosses the process boundary.
A POST failure (backend down, network blip) is logged and swallowed rather
than raised: CV is optional infrastructure, and a dashboard that can't reach
the backend right now is the backend's problem to surface, not a reason to
crash the CV process that has no user-facing surface of its own.

The POST runs on a background thread rather than on the caller's thread.
ADR 0002 decouples the 15 FPS analysis loop from the 1 Hz reporting rate,
and a synchronous POST breaks exactly that: an unreachable backend makes
every send block for the full timeout, dragging analysis down to the
timeout's rate. `submit()` hands the frame to a queue and returns, so a slow
or dead backend degrades reporting only.
"""

from __future__ import annotations

import logging
import queue
import threading
import time

import httpx

from contracts import DriverStateFrame

logger = logging.getLogger(__name__)

# Frames the send queue holds before it starts dropping. At 1 Hz this is
# several seconds of backlog — enough to ride out a brief stall, small
# enough that a long outage cannot grow the queue without bound.
MAX_QUEUED_FRAMES = 8

# Dropped-frame warnings are throttled to this interval: a dead backend
# drops one frame per second, and one log line per drop would bury the
# POST failures themselves.
DROP_LOG_INTERVAL_S = 10.0


class DriverStateClient:
    def __init__(self, base_url: str, timeout_s: float = 2.0) -> None:
        self._client = httpx.Client(base_url=base_url, timeout=timeout_s)
        self._queue: queue.Queue[DriverStateFrame | None] = queue.Queue(maxsize=MAX_QUEUED_FRAMES)
        self._dropped = 0
        self._last_drop_log = 0.0
        # Daemon: a POST wedged in a socket read must never keep the process
        # alive past shutdown.
        self._worker = threading.Thread(target=self._run, name="driver-state-sender", daemon=True)
        self._worker.start()

    def submit(self, frame: DriverStateFrame) -> None:
        """Queue `frame` for sending. Never blocks the caller.

        When the queue is full the *oldest* pending frame is discarded, not
        this one: driver state is a live signal, so the newest reading is
        the one worth keeping if the backend cannot keep up.
        """
        while True:
            try:
                self._queue.put_nowait(frame)
                return
            except queue.Full:
                try:
                    self._queue.get_nowait()
                except queue.Empty:
                    # The worker drained it between the two calls; retry.
                    continue
                self._note_drop()

    def _note_drop(self) -> None:
        self._dropped += 1
        now = time.monotonic()
        if now - self._last_drop_log >= DROP_LOG_INTERVAL_S:
            self._last_drop_log = now
            logger.warning(
                "Send queue full; dropped %d driver-state frame(s) so far (backend not keeping up)",
                self._dropped,
            )

    def _run(self) -> None:
        while True:
            frame = self._queue.get()
            if frame is None:  # shutdown sentinel
                return
            try:
                self.send(frame)
            except Exception:
                # `send` already swallows HTTP errors; anything reaching here
                # (e.g. the client closed underneath an in-flight POST at
                # shutdown) must not kill the worker silently.
                logger.exception("Driver-state send worker error")

    def send(self, frame: DriverStateFrame) -> bool:
        """POST one frame synchronously. Runs on the worker thread."""
        try:
            response = self._client.post(
                "/api/v1/ingest/driver-state", json=frame.model_dump(mode="json")
            )
            response.raise_for_status()
            return True
        except httpx.HTTPError as exc:
            logger.warning("Failed to POST driver state: %s", exc)
            return False

    def close(self) -> None:
        """Stop the worker and release the HTTP client.

        Joins only briefly: shutdown must not inherit the very stall this
        class exists to keep off the capture loop, so pending frames are
        abandoned rather than waited on.
        """
        # Enqueue the sentinel without blocking: a full queue at shutdown is
        # exactly the dead-backend case, and `put()` would wait on it.
        while True:
            try:
                self._queue.put_nowait(None)
                break
            except queue.Full:
                try:
                    self._queue.get_nowait()
                except queue.Empty:
                    continue

        self._worker.join(timeout=2.0)
        if self._worker.is_alive():
            logger.warning("Send worker still busy at shutdown; abandoning queued frames")
        if self._dropped:
            logger.info("Dropped %d driver-state frame(s) this session", self._dropped)
        self._client.close()
