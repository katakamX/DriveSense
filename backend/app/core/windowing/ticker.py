"""One 1 Hz inference tick per live trip.

Ingest is batch-shaped and the producer chooses the batch size; scoring must
not be, or the rate at which a driver sees their risk update would depend on
how the phone in their pocket decided to flush its queue. So scoring runs on
its own clock: one asyncio task per trip, started by the first frame that
arrives for that trip, waking every second to reduce the buffer's trailing 30
seconds to a `FeatureVector` and hand it to `app.ml.predict`.

The 30 s span is the span the model was trained on, and the features come from
`app.core.features.extract` — the same function the offline pipeline calls.
That is ADR 0004's whole point: the online path must not compute its own
version of a feature, so it does not.

**This is plumbing, not the risk engine.** The tick stores its most recent
result in a module-level dict and stops there. No risk score, no smoothing, no
WebSocket publishing — those come next, and the seam is `latest_inference`.

Lifecycle mirrors `app.core.events.state` and `app.core.live.broadcaster`:
created on first use, torn down when the trip ends or is deleted. Unlike a
dataclass in a dict, an abandoned task is a *running* leak — it would tick
forever over a buffer nobody feeds — so `stop_trip` cancels and awaits it, and
the application lifespan cancels whatever is left at shutdown.
"""

import asyncio
import contextlib
import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from app.config import get_settings
from app.core.features.extract import FeatureContext, extract_features
from app.core.features.schema import FeatureVector
from app.core.windowing import buffer
from app.ml import ModelOutput, predict

logger = logging.getLogger(__name__)

TICK_INTERVAL_S = 1.0

# A window this short cannot say anything meaningful, but it is not an error
# either — it is a trip that just started. Ticking anyway keeps the path warm
# and lets `coverage_ratio` carry the truth about window quality; deciding
# what coverage is good enough to *act* on belongs to the risk engine, not to
# the plumbing that produces the number.
MIN_SAMPLES = 2


@dataclass(frozen=True)
class TripInference:
    """The most recent tick's output for one trip.

    `model_output` is `None` when no artefact is loaded — a fresh checkout has
    no `model.json` (see `app.ml.loader`), and the tick still runs, still
    extracts features, and still records that it ran.
    """

    tick_index: int
    ticked_at: datetime
    window_start: datetime
    window_end: datetime
    sample_count: int
    coverage_ratio: float
    features: dict[str, float]
    model_output: ModelOutput | None


_tasks: dict[uuid.UUID, asyncio.Task[None]] = {}
_latest: dict[uuid.UUID, TripInference] = {}


def ensure_started(trip_id: uuid.UUID, speed_limit_kph: float) -> None:
    """Start the trip's tick if it isn't already running. Safe to call per batch.

    `speed_limit_kph` is captured at first frame: the event-derived features
    need it, and re-reading it per tick would mean touching the database from
    a background task for a value that does not change during a trip.
    """
    existing = _tasks.get(trip_id)
    if existing is not None and not existing.done():
        return
    task = asyncio.create_task(_run(trip_id, speed_limit_kph), name=f"inference-tick:{trip_id}")
    _tasks[trip_id] = task


async def stop_trip(trip_id: uuid.UUID) -> None:
    """Cancel the trip's tick, wait for it to actually stop, and release its buffer.

    Awaits the cancellation rather than firing and forgetting, so that by the
    time a trip is marked ended no further tick can observe its buffer — which
    is what makes releasing the buffer on the next line safe.
    """
    task = _tasks.pop(trip_id, None)
    if task is not None and not task.done():
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
    _latest.pop(trip_id, None)
    buffer.discard_trip(trip_id)


async def stop_all() -> None:
    """Tear down every running tick. For application shutdown."""
    for trip_id in list(_tasks):
        await stop_trip(trip_id)


def latest_inference(trip_id: uuid.UUID) -> TripInference | None:
    """The trip's most recent tick output, or `None` if it has not ticked yet.

    The seam the risk engine will consume. In-memory and last-value-only on
    purpose: nothing here is a system of record.
    """
    return _latest.get(trip_id)


def running_trip_count() -> int:
    """How many trips currently have a tick running. For tests and diagnostics."""
    return sum(1 for task in _tasks.values() if not task.done())


async def _run(trip_id: uuid.UUID, speed_limit_kph: float) -> None:
    settings = get_settings()
    expected_samples = buffer.WINDOW_SPAN_S * settings.telemetry_rate_hz
    tick_index = 0

    while True:
        await asyncio.sleep(TICK_INTERVAL_S)
        try:
            samples = buffer.snapshot(trip_id)
            if len(samples) < MIN_SAMPLES:
                continue

            coverage_ratio = len(samples) / expected_samples if expected_samples > 0 else 0.0
            vector: FeatureVector = extract_features(
                samples,
                FeatureContext(
                    speed_limit_kph=speed_limit_kph,
                    coverage_ratio=min(coverage_ratio, 1.0),
                ),
            )
            features = vector.as_dict()
            tick_index += 1
            output = predict(features)
            # DEBUG, not INFO: once per second per live trip. Enough to watch
            # the tick from a running server's logs without an endpoint to
            # query — which there deliberately is not yet.
            logger.debug(
                "trip %s tick %d: %d samples, coverage %.2f -> %s",
                trip_id,
                tick_index,
                vector.sample_count,
                vector.coverage_ratio,
                output.predicted_class if output is not None else "rule-only (no artefact)",
            )
            _latest[trip_id] = TripInference(
                tick_index=tick_index,
                ticked_at=datetime.now(UTC),
                window_start=vector.window_start,
                window_end=vector.window_end,
                sample_count=vector.sample_count,
                coverage_ratio=vector.coverage_ratio,
                features=features,
                model_output=output,
            )
        except Exception:
            # One bad window must not kill the trip's scoring for the rest of
            # the drive; log it and tick again in a second.
            logger.exception("Inference tick failed for trip %s", trip_id)
