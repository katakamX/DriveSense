"""Ramp concurrent trips against a live backend and measure latency/throughput.

Two things happen per trip, concurrently:

- A producer (`HttpSink`, `drivesense_sim.telemetry.sinks`) POSTs real-time
  paced telemetry batches over HTTP, the same path a real device would use.
- A consumer (`LiveTripListener`, `drivesense_bench.ws_listener`) holds a real
  WebSocket connection to that trip's live stream and stamps receive time per
  frame.

Ingest-to-browser latency for one frame is `received_at[seq] - sent_at[seq]`.
A frame the producer sent but the listener never saw counts as dropped rather
than silently missing -- under load that is the broadcaster's bounded queue
(`app.core.live.broadcaster._QUEUE_MAXSIZE`) discarding it, or the trip's
inference/publish path falling behind, and a benchmark that hid that would be
reporting a throughput number for traffic that never really arrived intact
(the same reasoning `HttpSink.frames_failed` documents for send failures).
"""

from __future__ import annotations

import asyncio
import math
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

from app.db.session import SessionLocal
from drivesense_bench.setup import create_trips, ensure_driver_and_vehicle
from drivesense_bench.ws_listener import LiveTripListener
from drivesense_sim.config import SimConfig, VehicleSpec
from drivesense_sim.drives import get_drive
from drivesense_sim.input.providers import ScriptedInputProvider
from drivesense_sim.source import SimulatorTelemetrySource
from drivesense_sim.telemetry.sinks import HttpSink

DEFAULT_LEVELS: tuple[int, ...] = (1, 2, 5, 10, 20, 40, 80)
LATENCY_TARGET_MS = 150.0

# How long the listener keeps the socket open after the producer sends its
# last frame. Covers the trailing 1 Hz risk tick and the final telemetry
# batch's own network round trip -- without it, frames sent in the last
# batch would be counted dropped just for arriving after we stopped looking.
DEFAULT_POST_RUN_GRACE_S = 2.0

# The vehicle used for every bench trip. Only its dynamics matter (there is
# nothing benchmark-specific about a hatchback); any spec in the simulator's
# library would do.
VEHICLE_SPEC = "hatchback"


def _widen_thread_pool(min_workers: int) -> None:
    """`asyncio.to_thread`'s default executor caps out at `min(32, cpu_count+4)`
    workers -- comfortably enough for ordinary background work, but a level
    with more concurrent trips than that would have producer threads queued
    waiting for a worker instead of running, which is a limit of this harness
    running on one machine, not of the backend under test. Sized to the
    ramp's top level so a measured degradation is never actually this."""
    loop = asyncio.get_running_loop()
    loop.set_default_executor(ThreadPoolExecutor(max_workers=min_workers + 4))


@dataclass
class TripResult:
    trip_id: uuid.UUID
    frames_sent: int
    frames_failed: int
    sent_at: dict[int, float]
    received_at: dict[int, float]
    risk_messages: int
    event_messages: int
    listener_connect_failed: bool


@dataclass
class LevelResult:
    concurrency: int
    wall_duration_s: float
    frames_sent: int
    frames_failed: int
    frames_dropped: int
    listener_connect_failures: int = 0
    latencies_ms: list[float] = field(default_factory=list)

    @property
    def throughput_fps(self) -> float:
        return self.frames_sent / self.wall_duration_s if self.wall_duration_s > 0 else 0.0

    @property
    def collapsed(self) -> bool:
        """No frame completed a round trip even though the level tried real
        work. `percentile()` returning `None` is ambiguous by itself -- an
        empty level (nothing attempted) and a level where every single send
        failed both produce it -- and conflating the two is exactly how a
        prior version of this report claimed p95 "stayed under target"
        through levels that had, in fact, produced zero successful frames."""
        return not self.latencies_ms and (self.frames_failed > 0 or self.frames_sent > 0)

    def percentile(self, p: float) -> float | None:
        return _percentile(self.latencies_ms, p)


def _percentile(values: list[float], p: float) -> float | None:
    """Linear-interpolation percentile (the same method `numpy.percentile`
    defaults to), so a result is comparable to one computed some other way."""
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    rank = (len(ordered) - 1) * p
    lo, hi = math.floor(rank), math.ceil(rank)
    if lo == hi:
        return ordered[int(rank)]
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (rank - lo)


def aggregate(concurrency: int, results: list[TripResult], wall_duration_s: float) -> LevelResult:
    frames_sent = sum(r.frames_sent for r in results)
    frames_failed = sum(r.frames_failed for r in results)
    listener_connect_failures = sum(1 for r in results if r.listener_connect_failed)
    latencies_ms: list[float] = []
    dropped = 0
    for result in results:
        for seq, sent in result.sent_at.items():
            received = result.received_at.get(seq)
            if received is None:
                dropped += 1
            else:
                latencies_ms.append((received - sent) * 1000.0)
    return LevelResult(
        concurrency=concurrency,
        wall_duration_s=wall_duration_s,
        frames_sent=frames_sent,
        frames_failed=frames_failed,
        frames_dropped=dropped,
        listener_connect_failures=listener_connect_failures,
        latencies_ms=latencies_ms,
    )


def _pump_trip_sync(
    base_url: str, backend_trip_id: uuid.UUID, drive: str, variant: str, duration_s: float
) -> HttpSink:
    """Runs in a worker thread: `HttpSink` and `frames(realtime=True)` are
    both synchronous/blocking, and a real-time-paced trip occupies its thread
    for the whole `duration_s` by design."""
    config = SimConfig()
    provider = ScriptedInputProvider(get_drive(drive, variant), config)
    source = SimulatorTelemetrySource(
        provider, VehicleSpec.load(VEHICLE_SPEC), config, duration_s=duration_s
    )
    meta = source.start(trip_id=f"bench-{backend_trip_id}")
    sink = HttpSink(base_url, str(backend_trip_id))
    sink.open(meta)
    try:
        for frame in source.frames(realtime=True):
            sink.write(frame)
    finally:
        sink.close()
        source.stop()
    return sink


async def run_trip(
    *,
    base_url: str,
    ws_base_url: str,
    backend_trip_id: uuid.UUID,
    drive: str,
    variant: str,
    duration_s: float,
    post_run_grace_s: float,
) -> TripResult:
    listener = LiveTripListener()
    stop = asyncio.Event()
    ws_url = f"{ws_base_url}/api/v1/trips/{backend_trip_id}/live"
    listen_task = asyncio.create_task(listener.run(ws_url, stop))
    # Let the socket connect and receive its snapshot before frames start
    # flowing, so the run doesn't lose the opening batch to a subscribe/
    # publish race.
    await asyncio.sleep(0.2)

    sink = await asyncio.to_thread(
        _pump_trip_sync, base_url, backend_trip_id, drive, variant, duration_s
    )

    await asyncio.sleep(post_run_grace_s)
    stop.set()
    await listen_task

    return TripResult(
        trip_id=backend_trip_id,
        frames_sent=sink.frames_sent,
        frames_failed=sink.frames_failed,
        sent_at=sink.sent_at,
        received_at=listener.received_at,
        risk_messages=listener.risk_messages,
        event_messages=listener.event_messages,
        listener_connect_failed=listener.connect_error is not None,
    )


async def run_level(
    *,
    base_url: str,
    ws_base_url: str,
    driver_id: uuid.UUID,
    vehicle_id: uuid.UUID,
    concurrency: int,
    drive: str,
    variant: str,
    duration_s: float,
    post_run_grace_s: float,
) -> LevelResult:
    async with SessionLocal() as session:
        trip_ids = await create_trips(session, driver_id, vehicle_id, concurrency)

    start = time.monotonic()
    results = await asyncio.gather(
        *[
            run_trip(
                base_url=base_url,
                ws_base_url=ws_base_url,
                backend_trip_id=trip_id,
                drive=drive,
                variant=variant,
                duration_s=duration_s,
                post_run_grace_s=post_run_grace_s,
            )
            for trip_id in trip_ids
        ]
    )
    wall_duration_s = time.monotonic() - start
    return aggregate(concurrency, results, wall_duration_s)


async def ramp(
    *,
    base_url: str,
    ws_base_url: str,
    levels: tuple[int, ...] = DEFAULT_LEVELS,
    drive: str = "demo",
    variant: str = "a",
    duration_s: float = 30.0,
    post_run_grace_s: float = DEFAULT_POST_RUN_GRACE_S,
    latency_target_ms: float = LATENCY_TARGET_MS,
) -> list[LevelResult]:
    """Run each concurrency level in turn, stopping once p95 crosses the target.

    This is a measurement, not a pass/fail test -- the target comes from
    `docs/architecture.md`'s exit criterion, not from a throughput number any
    document states, and there is none to check against. The ramp stops at
    the crossing because every level beyond it would only confirm what the
    first crossing already showed.
    """
    _widen_thread_pool(max(levels))
    async with SessionLocal() as session:
        driver_id, vehicle_id = await ensure_driver_and_vehicle(session)

    level_results: list[LevelResult] = []
    for concurrency in levels:
        result = await run_level(
            base_url=base_url,
            ws_base_url=ws_base_url,
            driver_id=driver_id,
            vehicle_id=vehicle_id,
            concurrency=concurrency,
            drive=drive,
            variant=variant,
            duration_s=duration_s,
            post_run_grace_s=post_run_grace_s,
        )
        level_results.append(result)
        p95 = result.percentile(0.95)
        if result.collapsed or (p95 is not None and p95 > latency_target_ms):
            break
    return level_results
