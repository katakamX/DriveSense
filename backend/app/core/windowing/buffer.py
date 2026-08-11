"""Bounded per-trip ring buffer of recent `FeatureSample`s.

The M4 window pipeline was specified with a ring buffer and built without one:
`make_windows` is a pure function over a list, deliberately ignorant of how the
samples arrived, and the offline pipeline hands it a whole recording. Online
inference cannot do that — frames arrive in HTTP batches whose size is the
producer's choice, and a 1 Hz tick needs the trailing 30 seconds regardless of
where the batch boundaries happened to fall. This is that missing piece: the
thing that turns a stream of batches back into a window.

Shape and lifecycle are copied deliberately from `app.core.events.state` — a
module-level dict keyed by trip id, valid because the topology is
single-worker (docs/adr/0003-defer-redis.md), created on first use, dropped
when a trip ends or is deleted. If that assumption breaks, this, the detector
state and the broadcaster all move to shared storage together.

Bounded because unbounded is a memory leak with a schedule: a trip that never
ends would otherwise accumulate frames until the process dies. `deque(maxlen)`
drops the oldest sample on overflow, which is the right loss — the tick only
ever reads the *trailing* span, so a dropped sample is one the next tick was
never going to look at.
"""

import uuid
from collections import deque
from collections.abc import Iterable
from datetime import timedelta

from app.core.features.schema import FeatureSample

# The trailing span a tick reduces to features. Matches
# `app.core.features.windows.DEFAULT_SPAN_S`, which is the span the model was
# trained on — the two must not drift, or serving windows stop meaning what
# training windows meant (ADR 0004).
WINDOW_SPAN_S = 30.0

# Room for twice the window at twice the nominal 10 Hz frame rate. Generous on
# purpose: the bound exists to cap memory for a trip that never ends, not to
# trim the window — that is `snapshot`'s job, and it works in seconds, not
# samples, so it stays correct whatever the producer's actual rate is.
MAX_SAMPLES = 1200

_buffers: dict[uuid.UUID, deque[FeatureSample]] = {}


def buffer_for(trip_id: uuid.UUID) -> deque[FeatureSample]:
    """The trip's buffer, created on first use."""
    buffer = _buffers.get(trip_id)
    if buffer is None:
        buffer = deque(maxlen=MAX_SAMPLES)
        _buffers[trip_id] = buffer
    return buffer


def append(trip_id: uuid.UUID, samples: Iterable[FeatureSample]) -> None:
    """Add a batch's frames to the trip's buffer, evicting the oldest if full."""
    buffer_for(trip_id).extend(samples)


def snapshot(trip_id: uuid.UUID, *, span_s: float = WINDOW_SPAN_S) -> list[FeatureSample]:
    """The trailing `span_s` of the trip's buffer, oldest first.

    The span is measured from the newest buffered sample's timestamp, not from
    wall-clock now: a tick that fires between batches must reduce the window
    the trip actually recorded, and replayed or slightly-delayed telemetry must
    produce the same features it would have live. Samples are assumed to arrive
    roughly in order, as every producer emits them; the cutoff is applied by
    timestamp, so a straggler inside the span still counts.
    """
    buffer = _buffers.get(trip_id)
    if not buffer:
        return []
    newest = max(sample.recorded_at for sample in buffer)
    cutoff = newest - timedelta(seconds=span_s)
    return sorted(
        (sample for sample in buffer if sample.recorded_at > cutoff),
        key=lambda sample: sample.recorded_at,
    )


def discard_trip(trip_id: uuid.UUID) -> None:
    """Release a finished or deleted trip's buffer."""
    _buffers.pop(trip_id, None)


def buffered_count(trip_id: uuid.UUID) -> int:
    """How many samples a trip currently holds. For tests and diagnostics."""
    buffer = _buffers.get(trip_id)
    return len(buffer) if buffer is not None else 0


def tracked_trip_count() -> int:
    """How many trips currently hold a buffer. For tests and diagnostics."""
    return len(_buffers)
