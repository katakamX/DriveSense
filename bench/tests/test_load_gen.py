"""`aggregate()` and `_percentile()` -- pure functions, no network.

`run_trip`/`run_level`/`ramp` need a live backend and a real database and are
exercised manually (`python -m drivesense_bench`), not here.
"""

from __future__ import annotations

import uuid

import pytest

from drivesense_bench.load_gen import LevelResult, TripResult, _percentile, aggregate


def make_result(sent_at: dict[int, float], received_at: dict[int, float]) -> TripResult:
    return TripResult(
        trip_id=uuid.uuid4(),
        frames_sent=len(sent_at),
        frames_failed=0,
        sent_at=sent_at,
        received_at=received_at,
        risk_messages=0,
        event_messages=0,
    )


def test_percentile_of_empty_list_is_none() -> None:
    assert _percentile([], 0.95) is None


def test_percentile_matches_a_known_case() -> None:
    values = [10.0, 20.0, 30.0, 40.0, 50.0]
    assert _percentile(values, 0.0) == 10.0
    assert _percentile(values, 1.0) == 50.0
    assert _percentile(values, 0.5) == 30.0


def test_aggregate_pairs_sent_and_received_by_seq() -> None:
    result = make_result(sent_at={1: 100.0, 2: 100.1}, received_at={1: 100.05, 2: 100.16})
    level = aggregate(concurrency=1, results=[result], wall_duration_s=1.0)

    assert level.frames_sent == 2
    assert level.frames_dropped == 0
    assert sorted(level.latencies_ms) == pytest.approx([50.0, 60.0])


def test_aggregate_counts_a_seq_never_seen_on_the_socket_as_dropped() -> None:
    result = make_result(sent_at={1: 100.0, 2: 100.1}, received_at={1: 100.05})
    level = aggregate(concurrency=1, results=[result], wall_duration_s=1.0)

    assert level.frames_dropped == 1
    assert level.latencies_ms == pytest.approx([50.0])


def test_aggregate_sums_across_concurrent_trips() -> None:
    a = make_result(sent_at={1: 100.0}, received_at={1: 100.05})
    b = make_result(sent_at={1: 200.0}, received_at={1: 200.05})
    level = aggregate(concurrency=2, results=[a, b], wall_duration_s=1.0)

    assert level.frames_sent == 2
    assert sorted(level.latencies_ms) == pytest.approx([50.0, 50.0])


def test_aggregate_counts_http_failures_separately_from_dropped_ws_frames() -> None:
    result = TripResult(
        trip_id=uuid.uuid4(),
        frames_sent=1,
        frames_failed=3,
        sent_at={1: 100.0},
        received_at={1: 100.05},
        risk_messages=0,
        event_messages=0,
    )
    level = aggregate(concurrency=1, results=[result], wall_duration_s=1.0)

    assert level.frames_failed == 3
    assert level.frames_dropped == 0


def test_throughput_is_frames_sent_over_wall_duration() -> None:
    level = LevelResult(
        concurrency=1, wall_duration_s=2.0, frames_sent=20, frames_failed=0, frames_dropped=0
    )
    assert level.throughput_fps == 10.0


def test_throughput_is_zero_for_a_zero_duration_run() -> None:
    level = LevelResult(
        concurrency=1, wall_duration_s=0.0, frames_sent=0, frames_failed=0, frames_dropped=0
    )
    assert level.throughput_fps == 0.0
