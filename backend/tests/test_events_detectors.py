"""Debounced event-detector tests.

Before debouncing, the only coverage these detectors had lived in
`test_features_extract.py`, and it was relational — it asserted the feature
equalled `len(detector(...)) / duration`, so both sides moved together and
any counting rule passed. Nothing pinned what "one event" actually meant.
These tests pin it.

The two behaviours that motivated the change (see
ml/reports/m7b-simulator-generation-pilot-and-bulk.md) are the first two
cases: a sustained deceleration must be one event, and isolated noise dips
must be none.
"""

import uuid
from datetime import UTC, datetime, timedelta

from app.core.events import state as event_state
from app.core.events.detectors import (
    FrameSample,
    TripDetectorState,
    detect_events,
    detect_harsh_braking,
    detect_rapid_acceleration,
    detect_speeding,
    flush_events,
)
from app.core.events.thresholds import (
    HARSH_BRAKING_ACCEL_MS2,
    MIN_EVENT_FRAMES,
    MIN_RELEASE_FRAMES,
)

T0 = datetime(2026, 1, 1, tzinfo=UTC)
DT = 0.1  # 10 Hz


def _frames(accels: list[float], *, start_id: int = 0, speed: float = 50.0) -> list[FrameSample]:
    return [
        FrameSample(
            telemetry_id=start_id + i,
            recorded_at=T0 + timedelta(seconds=(start_id + i) * DT),
            accel_ms2=a,
            speed_kph=speed,
        )
        for i, a in enumerate(accels)
    ]


# --- The two cases that motivated debouncing --------------------------------


def test_sustained_deceleration_is_one_event_not_one_per_frame() -> None:
    # 20 consecutive frames past -3.5, as clean simulator physics produces.
    frames = _frames([0.0] + [-4.5] * 20 + [0.0] * 10)

    events = detect_harsh_braking(frames)

    assert len(events) == 1
    assert events[0].event_type == "harsh_braking"
    assert events[0].frame_count == 20


def test_isolated_noise_dips_are_not_events() -> None:
    # Single-sample crossings scattered through a window, as a noisy real
    # accelerometer produces during one real brake. None persists for
    # MIN_EVENT_FRAMES, so none is an event.
    accels = [-1.0, -4.0, -1.0, -1.0, -5.0, -1.0, -3.6, -1.0, -4.2, -1.0]

    assert detect_harsh_braking(_frames(accels)) == []


def test_a_crossing_one_frame_short_of_the_minimum_is_not_an_event() -> None:
    frames = _frames([0.0] + [-4.0] * (MIN_EVENT_FRAMES - 1) + [0.0] * 10)

    assert detect_harsh_braking(frames) == []


def test_a_crossing_exactly_at_the_minimum_is_an_event() -> None:
    frames = _frames([0.0] + [-4.0] * MIN_EVENT_FRAMES + [0.0] * 10)

    events = detect_harsh_braking(frames)

    assert len(events) == 1
    assert events[0].frame_count == MIN_EVENT_FRAMES


# --- Hysteresis -------------------------------------------------------------


def test_a_brief_easing_inside_the_hysteresis_band_does_not_split_the_event() -> None:
    # Dips to -3.0: past the -2.5 release line is what closes an event, and
    # -3.0 is not past it, so this stays one brake.
    frames = _frames([0.0] + [-4.5] * 5 + [-3.0] * 3 + [-4.5] * 5 + [0.0] * 10)

    events = detect_harsh_braking(frames)

    assert len(events) == 1


def test_a_full_recovery_closes_the_event_and_a_later_brake_is_a_second_event() -> None:
    frames = _frames(
        [0.0]
        + [-4.5] * 5
        + [0.0] * MIN_RELEASE_FRAMES  # sustained recovery past -2.5
        + [-4.5] * 5
        + [0.0] * 10
    )

    events = detect_harsh_braking(frames)

    assert len(events) == 2


def test_recovery_shorter_than_the_release_minimum_does_not_close_the_event() -> None:
    frames = _frames(
        [0.0] + [-4.5] * 5 + [0.0] * (MIN_RELEASE_FRAMES - 1) + [-4.5] * 5 + [0.0] * 10
    )

    assert len(detect_harsh_braking(frames)) == 1


# --- Anchoring --------------------------------------------------------------


def test_event_is_onset_anchored_but_reports_the_peak_value() -> None:
    frames = _frames([0.0, -3.6, -4.0, -6.2, -4.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0])

    (event,) = detect_harsh_braking(frames)

    # Onset is the first frame past the threshold (index 1), not the peak.
    assert event.telemetry_id == 1
    assert event.recorded_at == T0 + timedelta(seconds=DT)
    # measured_value is the most extreme value reached, not the onset's.
    assert event.measured_value == -6.2
    assert event.threshold_value == HARSH_BRAKING_ACCEL_MS2


# --- Rapid acceleration mirrors braking -------------------------------------


def test_sustained_rapid_acceleration_is_one_event() -> None:
    frames = _frames([0.0] + [3.6] * 15 + [0.0] * 10)

    events = detect_rapid_acceleration(frames)

    assert len(events) == 1
    assert events[0].event_type == "rapid_acceleration"
    assert events[0].measured_value == 3.6


def test_isolated_acceleration_spikes_are_not_events() -> None:
    assert detect_rapid_acceleration(_frames([0.0, 3.5, 0.0, 4.0, 0.0, 3.2, 0.0])) == []


# --- Speeding is deliberately not debounced ---------------------------------


def test_speeding_stays_one_event_per_frame() -> None:
    # speeding_time_ratio divides this count by the frame count to get a time
    # fraction, so coalescing here would silently redefine that feature.
    frames = _frames([0.0] * 6, speed=130.0)

    events = detect_speeding(frames, speed_limit_kph=100.0)

    assert len(events) == 6


# --- Batch-boundary continuity ----------------------------------------------


def test_a_brake_spanning_two_batches_is_one_event() -> None:
    state = TripDetectorState()
    first = _frames([0.0] + [-4.5] * 9, start_id=0)
    second = _frames([-4.5] * 5 + [0.0] * 10, start_id=10)

    events = detect_harsh_braking(first, state=state) + detect_harsh_braking(second, state=state)

    assert len(events) == 1
    assert events[0].telemetry_id == 1  # onset is in the first batch


def test_without_state_the_same_split_is_miscounted_as_two_events() -> None:
    # Documents exactly what the per-trip state buys: the stateless calls
    # each flush their own open event at the end of their frame list.
    first = _frames([0.0] + [-4.5] * 9, start_id=0)
    second = _frames([-4.5] * 5 + [0.0] * 10, start_id=10)

    events = detect_harsh_braking(first) + detect_harsh_braking(second)

    assert len(events) == 2


def test_an_event_open_at_the_end_of_a_batch_is_not_emitted_until_it_closes() -> None:
    state = TripDetectorState()
    frames = _frames([0.0] + [-4.5] * 9)

    # Still braking when the batch ends: nothing to report yet.
    assert detect_harsh_braking(frames, state=state) == []
    # ...and the recovery in the next batch closes it.
    assert len(detect_harsh_braking(_frames([0.0] * 10, start_id=10), state=state)) == 1


def test_flush_closes_an_event_left_open_when_a_trip_ends() -> None:
    state = TripDetectorState()
    detect_harsh_braking(_frames([0.0] + [-4.5] * 9), state=state)

    events = flush_events(state)

    assert len(events) == 1
    assert events[0].event_type == "harsh_braking"


def test_stateless_calls_flush_so_a_whole_recording_loses_no_trailing_event() -> None:
    # The offline path passes no state: the frame list is the whole recording,
    # so a brake still in progress at the last frame is real and must count.
    assert len(detect_harsh_braking(_frames([0.0] + [-4.5] * 9))) == 1


# --- Per-trip state registry ------------------------------------------------


def test_state_registry_is_per_trip_and_released_on_flush() -> None:
    trip_a, trip_b = uuid.uuid4(), uuid.uuid4()

    assert event_state.state_for(trip_a) is not event_state.state_for(trip_b)
    assert event_state.state_for(trip_a) is event_state.state_for(trip_a)

    event_state.flush_trip(trip_a)
    event_state.discard_trip(trip_b)

    assert event_state.tracked_trip_count() == 0


def test_two_trips_braking_at_once_do_not_share_debounce_state() -> None:
    trip_a, trip_b = uuid.uuid4(), uuid.uuid4()
    try:
        detect_harsh_braking(_frames([-4.5] * 2), state=event_state.state_for(trip_a))
        # Only 2 frames each: neither reaches MIN_EVENT_FRAMES on its own, and
        # they must not add up across trips.
        detect_harsh_braking(_frames([-4.5] * 2), state=event_state.state_for(trip_b))

        assert event_state.flush_trip(trip_a) == []
        assert event_state.flush_trip(trip_b) == []
    finally:
        event_state.discard_trip(trip_a)
        event_state.discard_trip(trip_b)


# --- detect_events composition ----------------------------------------------


def test_detect_events_combines_debounced_impulses_with_per_frame_speeding() -> None:
    frames = _frames([-4.5] * 6 + [0.0] * 10, speed=130.0)

    events = detect_events(frames, speed_limit_kph=100.0)

    by_type = {e.event_type: [x for x in events if x.event_type == e.event_type] for e in events}
    assert len(by_type["harsh_braking"]) == 1
    assert len(by_type["speeding"]) == 16
