"""In-process per-trip detector state, so debounced events survive batching.

`detect_events` is called once per ingest HTTP batch. Frame-counted events
were batch-invariant; debounced ones are not — a brake spanning two batches
would be reported as two events unless the open event is carried across the
boundary. That would make event counts depend on the producer's batching
cadence, and would make the live path disagree with the offline path (which
sees a whole recording at once) — reintroducing exactly the training/serving
skew ADR 0004 exists to prevent.

Same shape and same justification as `app.core.live.broadcaster`: a
module-level dict keyed by trip id, valid because the topology is
single-worker (docs/adr/0003-defer-redis.md). If that assumption ever
breaks, this and the broadcaster move to shared storage together.

State is created on first use, and dropped when a trip ends or is deleted.
A trip that is abandoned without either leaks one small dataclass until the
process restarts; that is the same bounded, accepted leak the broadcaster
has, and is not worth a reaper at this scale.
"""

import uuid

from app.core.events.detectors import DetectedEvent, TripDetectorState, flush_events

_states: dict[uuid.UUID, TripDetectorState] = {}


def state_for(trip_id: uuid.UUID) -> TripDetectorState:
    """The trip's detector state, created on first use."""
    return _states.setdefault(trip_id, TripDetectorState())


def flush_trip(trip_id: uuid.UUID) -> list[DetectedEvent]:
    """Close any in-progress event for a finished trip and forget the state.

    Returns the trailing events so the caller can persist them; an event
    still open when the last batch arrived is real driving and must not be
    dropped just because the trip ended mid-brake.
    """
    state = _states.pop(trip_id, None)
    if state is None:
        return []
    return flush_events(state)


def discard_trip(trip_id: uuid.UUID) -> None:
    """Forget a trip's state without emitting anything (trip deleted)."""
    _states.pop(trip_id, None)


def tracked_trip_count() -> int:
    """How many trips currently hold detector state. For tests and diagnostics."""
    return len(_states)
