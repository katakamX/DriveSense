"""Receive-side timer for `/trips/{id}/live`.

Pairs with `HttpSink.sent_at` (`drivesense_sim.telemetry.sinks`): the sink
stamps wall-clock send time per frame keyed by `seq` when it POSTs a batch;
`LiveTripListener` stamps wall-clock receive time for the same key when the
backend echoes that frame back over the WebSocket. Ingest -> browser latency
for one frame is then `received_at[seq] - sent_at[seq]`, two dict lookups
apart rather than inferred from server-side logs.

A real `websockets` connection against the deployed backend, not Starlette's
in-process `TestClient` the backend's own tests use — the thing being
measured is network-and-process time, which an in-process test client does
not have.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field

import websockets

logger = logging.getLogger(__name__)


@dataclass
class LiveTripListener:
    """Subscribes to one trip's live stream and records arrival times.

    Counts of the other message types are kept so a benchmark run can report
    on them without decoding every message a second time; `unrecognized`
    catches anything that isn't one of the types `LiveMessage` names, which
    should stay 0 and signals a protocol drift if it doesn't.
    """

    received_at: dict[int, float] = field(default_factory=dict)
    risk_messages: int = 0
    event_messages: int = 0
    snapshot_messages: int = 0
    ping_messages: int = 0
    unrecognized: int = 0
    connect_error: str | None = None

    async def run(self, ws_url: str, stop: asyncio.Event) -> None:
        """Connect and pump messages until `stop` is set or the socket closes.

        Never raises. A connection that never opens (refused, or the
        handshake timing out under load -- the failure this is guarding
        against, seen when the load generator's own ramp pushed concurrency
        high enough to starve the accept path) is exactly the kind of thing a
        benchmark run needs to survive and report, not crash on -- the same
        reasoning `HttpSink` documents for send failures. `received_at`
        simply stays empty, which `load_gen.aggregate` already reports as
        every one of this trip's frames dropped.
        """
        try:
            async with websockets.connect(ws_url) as ws:
                pump_task = asyncio.create_task(self._pump(ws))
                stop_task = asyncio.create_task(stop.wait())
                try:
                    await asyncio.wait({pump_task, stop_task}, return_when=asyncio.FIRST_COMPLETED)
                finally:
                    pump_task.cancel()
                    stop_task.cancel()
                    await asyncio.gather(pump_task, stop_task, return_exceptions=True)
        except Exception as exc:
            logger.warning("Live socket %s failed: %s", ws_url, exc)
            self.connect_error = str(exc)

    async def _pump(self, ws: websockets.ClientConnection) -> None:
        async for raw in ws:
            self._handle(raw)

    def _handle(self, raw: str | bytes) -> None:
        try:
            message = json.loads(raw)
        except (TypeError, ValueError):
            logger.warning("Non-JSON message on live socket: %r", raw)
            self.unrecognized += 1
            return

        received_wall_time = time.time()
        msg_type = message.get("type")
        if msg_type == "telemetry":
            seq = message.get("data", {}).get("seq")
            if seq is not None:
                self.received_at[int(seq)] = received_wall_time
        elif msg_type == "risk":
            self.risk_messages += 1
        elif msg_type == "event":
            self.event_messages += 1
        elif msg_type == "snapshot":
            self.snapshot_messages += 1
        elif msg_type == "ping":
            self.ping_messages += 1
        else:
            self.unrecognized += 1
