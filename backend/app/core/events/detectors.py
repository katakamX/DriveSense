"""Pure, deterministic driving-event detectors.

No DB access here — these take plain data in and return plain data out. The
caller is responsible for turning the result into persisted rows.

**Impulse events are debounced; state events are not.** Harsh braking and
rapid acceleration are *impulses*: a brake application is one event however
many frames it spans, so those two run through a hysteresis state machine
(see `thresholds`). Speeding is a *sustained state*, not an impulse — and
`app.core.features.extract.speeding_time_ratio` divides its event count by
the frame count to get a time fraction, which only means anything if
speeding stays one-event-per-frame. That asymmetry is deliberate; changing
it would silently redefine a feature.

Two calling patterns, one implementation:

- **Offline / whole recording** (`ml/pipelines/featurise.py` via
  `app.core.features.extract`): call without `state`. Every event that is
  still open when the frames run out is flushed and returned, because there
  is no "next batch" coming.
- **Live / per HTTP batch** (`app.api.v1.telemetry`): pass the trip's
  `TripDetectorState`. An event still open at the end of a batch stays open
  and is carried into the next call, so a brake spanning a batch boundary is
  one event rather than two. Without this, event counts would depend on the
  ingest batching cadence — see `app.core.events.state`.
"""

from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import datetime

from app.core.events.thresholds import (
    HARSH_BRAKING_ACCEL_MS2,
    HARSH_BRAKING_RELEASE_ACCEL_MS2,
    MIN_EVENT_FRAMES,
    MIN_RELEASE_FRAMES,
    RAPID_ACCELERATION_ACCEL_MS2,
    RAPID_ACCELERATION_RELEASE_ACCEL_MS2,
    SPEEDING_MARGIN_KPH,
)


@dataclass(frozen=True)
class FrameSample:
    """The subset of a telemetry frame detectors need, keyed to its stored row."""

    telemetry_id: int
    recorded_at: datetime
    accel_ms2: float
    speed_kph: float


@dataclass(frozen=True)
class DetectedEvent:
    """One detected event.

    For debounced impulse events (harsh braking, rapid acceleration) this
    spans several frames, and the anchoring is deliberately split:

    - `telemetry_id` / `recorded_at` are **onset-anchored** — "when did the
      harsh brake happen" is when it started, and an onset does not move as
      the event develops, so a timeline entry stays put.
    - `measured_value` is **peak-anchored** — the most extreme acceleration
      reached during the event. The onset frame is by definition barely past
      the threshold, so reporting its value would make every event read
      ~-3.5 and understate severity uniformly.

    `frame_count` and `ended_at` describe the event's extent. They are not
    persisted by `DrivingEvent` today (its columns predate debouncing); they
    are carried here so a caller that wants duration does not have to
    re-derive it.
    """

    telemetry_id: int
    recorded_at: datetime
    event_type: str
    measured_value: float
    threshold_value: float
    frame_count: int = 1
    ended_at: datetime | None = None


@dataclass
class _ImpulseState:
    """Resumable debounce state for one impulse detector.

    Mutable by design: it is carried across batch calls (see
    `app.core.events.state`). `candidate_*` holds a crossing that has not yet
    persisted for `MIN_EVENT_FRAMES` — the noise-rejection buffer.
    """

    active: bool = False
    onset: FrameSample | None = None
    peak_value: float = 0.0
    frame_count: int = 0
    release_run: int = 0
    last_frame: FrameSample | None = None

    candidate_onset: FrameSample | None = None
    candidate_peak: float = 0.0
    candidate_count: int = 0

    def _reset(self) -> None:
        self.active = False
        self.onset = None
        self.peak_value = 0.0
        self.frame_count = 0
        self.release_run = 0
        self.last_frame = None

    def _drop_candidate(self) -> None:
        self.candidate_onset = None
        self.candidate_peak = 0.0
        self.candidate_count = 0


@dataclass
class TripDetectorState:
    """Per-trip debounce state for the impulse detectors.

    One instance per in-flight trip, held by `app.core.events.state` for the
    live path. Speeding needs no state: it is evaluated per frame.
    """

    braking: _ImpulseState = field(default_factory=_ImpulseState)
    acceleration: _ImpulseState = field(default_factory=_ImpulseState)


def _run_impulse_detector(
    frames: list[FrameSample],
    state: _ImpulseState,
    *,
    event_type: str,
    trigger: float,
    release: float,
    braking: bool,
    flush: bool,
) -> Iterator[DetectedEvent]:
    """Debounced threshold crossings -> events.

    `braking` flips the comparison direction: braking triggers on values at
    or below `trigger`, acceleration on values at or above it.
    """

    def past_trigger(value: float) -> bool:
        return value <= trigger if braking else value >= trigger

    def past_release(value: float) -> bool:
        return value > release if braking else value < release

    def more_extreme(value: float, current: float) -> bool:
        return value < current if braking else value > current

    def emit() -> DetectedEvent:
        assert state.onset is not None
        return DetectedEvent(
            telemetry_id=state.onset.telemetry_id,
            recorded_at=state.onset.recorded_at,
            event_type=event_type,
            measured_value=state.peak_value,
            threshold_value=trigger,
            frame_count=state.frame_count,
            ended_at=state.last_frame.recorded_at if state.last_frame else None,
        )

    for frame in frames:
        value = frame.accel_ms2

        if not state.active:
            if past_trigger(value):
                if state.candidate_onset is None:
                    state.candidate_onset = frame
                    state.candidate_peak = value
                elif more_extreme(value, state.candidate_peak):
                    state.candidate_peak = value
                state.candidate_count += 1

                if state.candidate_count >= MIN_EVENT_FRAMES:
                    state.active = True
                    state.onset = state.candidate_onset
                    state.peak_value = state.candidate_peak
                    state.frame_count = state.candidate_count
                    state.release_run = 0
                    state.last_frame = frame
                    state._drop_candidate()
            else:
                # A crossing that did not persist. This is the isolated
                # sensor-noise dip the debounce exists to reject.
                state._drop_candidate()
            continue

        state.frame_count += 1
        state.last_frame = frame
        if more_extreme(value, state.peak_value):
            state.peak_value = value

        if past_release(value):
            state.release_run += 1
            if state.release_run >= MIN_RELEASE_FRAMES:
                # The release frames are recovery, not part of the event.
                state.frame_count -= state.release_run
                yield emit()
                state._reset()
        else:
            # Inside the hysteresis band (or back past the trigger): still
            # the same event.
            state.release_run = 0

    if flush and state.active:
        yield emit()
        state._reset()


def detect_harsh_braking(
    frames: list[FrameSample], *, state: TripDetectorState | None = None
) -> list[DetectedEvent]:
    """Debounced harsh-braking events.

    Without `state`, the frame list is treated as complete and any event
    still open at the end is flushed. With `state`, an open event is carried
    into the next call instead.
    """
    impulse = state.braking if state else _ImpulseState()
    return list(
        _run_impulse_detector(
            frames,
            impulse,
            event_type="harsh_braking",
            trigger=HARSH_BRAKING_ACCEL_MS2,
            release=HARSH_BRAKING_RELEASE_ACCEL_MS2,
            braking=True,
            flush=state is None,
        )
    )


def detect_rapid_acceleration(
    frames: list[FrameSample], *, state: TripDetectorState | None = None
) -> list[DetectedEvent]:
    """Debounced rapid-acceleration events. See `detect_harsh_braking`."""
    impulse = state.acceleration if state else _ImpulseState()
    return list(
        _run_impulse_detector(
            frames,
            impulse,
            event_type="rapid_acceleration",
            trigger=RAPID_ACCELERATION_ACCEL_MS2,
            release=RAPID_ACCELERATION_RELEASE_ACCEL_MS2,
            braking=False,
            flush=state is None,
        )
    )


def detect_speeding(frames: list[FrameSample], speed_limit_kph: float) -> list[DetectedEvent]:
    """One event per frame over the limit — deliberately *not* debounced.

    Speeding is a sustained state rather than an impulse, and
    `app.core.features.extract.speeding_time_ratio` reads this count as a
    fraction of frames. Coalescing here would turn that feature from a time
    fraction into an event rate without the name changing.
    """
    threshold = speed_limit_kph + SPEEDING_MARGIN_KPH
    return [
        DetectedEvent(f.telemetry_id, f.recorded_at, "speeding", f.speed_kph, threshold)
        for f in frames
        if f.speed_kph > threshold
    ]


def detect_events(
    frames: list[FrameSample],
    speed_limit_kph: float,
    *,
    state: TripDetectorState | None = None,
) -> list[DetectedEvent]:
    return [
        *detect_harsh_braking(frames, state=state),
        *detect_rapid_acceleration(frames, state=state),
        *detect_speeding(frames, speed_limit_kph),
    ]


def flush_events(state: TripDetectorState) -> list[DetectedEvent]:
    """Close any event still open in `state` and return it.

    Called when a trip ends: an event in progress at the final batch would
    otherwise never be emitted, since the live path never flushes on its own.
    """
    return [
        *_run_impulse_detector(
            [],
            state.braking,
            event_type="harsh_braking",
            trigger=HARSH_BRAKING_ACCEL_MS2,
            release=HARSH_BRAKING_RELEASE_ACCEL_MS2,
            braking=True,
            flush=True,
        ),
        *_run_impulse_detector(
            [],
            state.acceleration,
            event_type="rapid_acceleration",
            trigger=RAPID_ACCELERATION_ACCEL_MS2,
            release=RAPID_ACCELERATION_RELEASE_ACCEL_MS2,
            braking=False,
            flush=True,
        ),
    ]
