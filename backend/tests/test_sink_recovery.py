"""What a trip's final verdict is worth when the process that scored it restarted.

The bug these guard against is silent, which is why it is worth its own module.
`_accumulators` is memory; a restart empties it; and a trip that was half over
when that happened would previously be summarised from only the windows scored
after the restart — a number that looks entirely ordinary and describes the
wrong drive.

A restart is simulated with `discard_trip`, which drops exactly what a process
death drops (the accumulator, the pending queue) and leaves exactly what
survives it (the rows already written). No subprocess required: the seam is the
module's own state, and it is reachable directly.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import AsyncIterator

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.risk import sink as risk_sink
from app.core.risk.aggregate import summarise
from app.core.risk.schema import RiskAssessment, RiskBand
from app.db.models import Trip
from app.db.session import engine
from tests.test_risk_sink import CALM_WINDOW, HIGH_RISK_WINDOW, count_rows, make_trip, window


@pytest.fixture
async def bound_sink() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    """A sink writing into a transaction this fixture rolls back."""
    connection = await engine.connect()
    transaction = await connection.begin()
    factory = async_sessionmaker(
        bind=connection, expire_on_commit=False, join_transaction_mode="create_savepoint"
    )
    risk_sink.reset()
    risk_sink.set_session_factory(factory)
    try:
        yield factory
    finally:
        risk_sink.reset()
        await transaction.rollback()
        await connection.close()


async def persist(trip_id: uuid.UUID, assessments: list[RiskAssessment]) -> None:
    """Enqueue and write, leaving the accumulator holding them all."""
    for assessment in assessments:
        risk_sink.enqueue(trip_id, assessment)
    await risk_sink.flush(trip_id)


def restart(trip_id: uuid.UUID) -> None:
    """Everything a process death takes with it. The rows stay where they are."""
    risk_sink.discard_trip(trip_id)


REBUILD_LOGGER = "app.core.risk.sink"


def rebuilt(caplog: pytest.LogCaptureFixture) -> bool:
    return any("rebuilding the summary" in record.message for record in caplog.records)


# --- the restart cases --------------------------------------------------------


async def test_a_summary_survives_a_restart_part_way_through_a_trip(
    bound_sink: async_sessionmaker[AsyncSession], caplog: pytest.LogCaptureFixture
) -> None:
    """The half the accumulator never saw still counts toward the verdict."""
    trip_id = await make_trip(bound_sink)
    before = [window(CALM_WINDOW, index=index) for index in range(3)]
    await persist(trip_id, before)

    restart(trip_id)
    assert risk_sink.accumulator_for(trip_id) is None

    after = [window(HIGH_RISK_WINDOW, index=index) for index in range(3, 5)]
    for assessment in after:
        risk_sink.enqueue(trip_id, assessment)
    # The partial accumulator is the trap: it exists, it is internally
    # consistent, and it describes two windows out of five.
    accumulator = risk_sink.accumulator_for(trip_id)
    assert accumulator is not None
    assert accumulator.window_count == 2

    with caplog.at_level(logging.WARNING, logger=REBUILD_LOGGER):
        summary = await risk_sink.finalise_trip(trip_id)

    assert rebuilt(caplog)
    assert summary is not None
    assert summary.window_count == 5
    assert await count_rows(bound_sink, trip_id) == 5

    expected = summarise(before + after)
    assert summary.trip_score == pytest.approx(expected.trip_score, abs=0.01)
    assert summary.max_score == pytest.approx(expected.max_score, abs=0.01)
    assert summary.band_counts == expected.band_counts
    assert summary.high_risk_window_ratio == pytest.approx(expected.high_risk_window_ratio)


async def test_a_trip_with_no_surviving_memory_is_summarised_from_the_table_alone(
    bound_sink: async_sessionmaker[AsyncSession], caplog: pytest.LogCaptureFixture
) -> None:
    """The literal restart-then-end case: nothing in memory, five rows on disk."""
    trip_id = await make_trip(bound_sink)
    assessments = [
        window(CALM_WINDOW, index=0),
        window(CALM_WINDOW, index=1),
        window(HIGH_RISK_WINDOW, index=2),
        window(CALM_WINDOW, index=3),
        window(HIGH_RISK_WINDOW, index=4),
    ]
    await persist(trip_id, assessments)
    restart(trip_id)

    with caplog.at_level(logging.WARNING, logger=REBUILD_LOGGER):
        summary = await risk_sink.finalise_trip(trip_id)

    assert rebuilt(caplog)
    assert summary is not None

    expected = summarise(assessments)
    assert summary.window_count == expected.window_count
    assert summary.trip_band == expected.trip_band
    assert summary.band_counts == expected.band_counts
    assert summary.trip_score == pytest.approx(expected.trip_score, abs=0.01)
    assert summary.mean_score == pytest.approx(expected.mean_score, abs=0.01)
    assert summary.max_score == pytest.approx(expected.max_score, abs=0.01)
    assert summary.gated_window_ratio == pytest.approx(expected.gated_window_ratio)
    assert summary.model_window_ratio == pytest.approx(expected.model_window_ratio)
    assert summary.first_window_start == expected.first_window_start
    assert summary.last_window_end == expected.last_window_end


async def test_the_rebuilt_summary_reaches_the_trip_row(
    bound_sink: async_sessionmaker[AsyncSession],
) -> None:
    """A recovered verdict is only worth anything if it is the one that gets stamped."""
    trip_id = await make_trip(bound_sink)
    await persist(trip_id, [window(HIGH_RISK_WINDOW, index=index) for index in range(4)])
    restart(trip_id)

    summary = await risk_sink.finalise_trip(trip_id)
    assert summary is not None

    async with bound_sink() as session:
        trip = await session.get(Trip, trip_id)
        assert trip is not None
        assert trip.risk_band == RiskBand.HIGH_RISK.value
        assert trip.risk_score is not None
        assert float(trip.risk_score) == pytest.approx(summary.trip_score or 0.0, abs=0.01)
        assert trip.risk_engine_version == summary.risk_engine_version


async def test_a_model_backed_window_round_trips_through_the_rebuild(
    bound_sink: async_sessionmaker[AsyncSession],
) -> None:
    """`model_available` and `gated` drive two of the summary's ratios.

    They are booleans on the row rather than numbers, so a rebuild that dropped
    or defaulted them would still produce a plausible-looking summary — the
    ratios would simply read zero.
    """
    trip_id = await make_trip(bound_sink)
    assessments = [window({"speed_mean": 200.0}, index=index, use_model=True) for index in range(3)]
    await persist(trip_id, assessments)
    restart(trip_id)

    summary = await risk_sink.finalise_trip(trip_id)
    expected = summarise(assessments)
    assert summary is not None
    assert summary.model_window_ratio == pytest.approx(expected.model_window_ratio)
    assert summary.gated_window_ratio == pytest.approx(expected.gated_window_ratio)
    assert summary.model_window_ratio == 1.0


# --- and the paths that must not change ---------------------------------------


async def test_the_intact_path_does_not_touch_the_table(
    bound_sink: async_sessionmaker[AsyncSession], caplog: pytest.LogCaptureFixture
) -> None:
    """Memory is authoritative when it is complete: no rebuild, no rounding.

    Asserted through the log rather than the numbers because the two summaries
    agree to well within the columns' precision — which is the point, and also
    what makes the difference invisible to an assertion on the score.
    """
    trip_id = await make_trip(bound_sink)
    for index in range(3):
        risk_sink.enqueue(trip_id, window(CALM_WINDOW, index=index))

    with caplog.at_level(logging.WARNING, logger=REBUILD_LOGGER):
        summary = await risk_sink.finalise_trip(trip_id)

    assert not rebuilt(caplog)
    assert summary is not None
    assert summary.window_count == 3


async def test_an_unwritten_tail_leaves_memory_ahead_of_the_table(
    bound_sink: async_sessionmaker[AsyncSession], caplog: pytest.LogCaptureFixture
) -> None:
    """The accumulator legitimately runs ahead of the rows; that is not a restart.

    `enqueue` folds before the row is written, so between a flush and the next
    one memory holds more windows than the table does. The reconciliation test
    is `>=` for exactly this case, and reading it as damage would replace a
    correct summary with an incomplete one.
    """
    trip_id = await make_trip(bound_sink)
    await persist(trip_id, [window(CALM_WINDOW, index=0)])
    risk_sink.enqueue(trip_id, window(HIGH_RISK_WINDOW, index=1))
    assert await count_rows(bound_sink, trip_id) == 1

    with caplog.at_level(logging.WARNING, logger=REBUILD_LOGGER):
        summary = await risk_sink.finalise_trip(trip_id)

    assert not rebuilt(caplog)
    assert summary is not None
    assert summary.window_count == 2
    assert await count_rows(bound_sink, trip_id) == 2


async def test_a_trip_that_never_scored_still_gets_no_verdict(
    bound_sink: async_sessionmaker[AsyncSession],
) -> None:
    """Reading the table for a trip with no rows must not invent a zero."""
    trip_id = await make_trip(bound_sink)
    restart(trip_id)
    assert await risk_sink.finalise_trip(trip_id) is None

    async with bound_sink() as session:
        trip = await session.get(Trip, trip_id)
        assert trip is not None
        assert trip.risk_score is None
        assert trip.risk_band is None


async def test_recovery_works_inside_a_caller_supplied_transaction(
    bound_sink: async_sessionmaker[AsyncSession],
) -> None:
    """The real trip-end path passes the request's session; the rebuild must read it.

    Including the rows this same call just flushed, which are in the caller's
    transaction and not yet committed.
    """
    trip_id = await make_trip(bound_sink)
    await persist(trip_id, [window(CALM_WINDOW, index=index) for index in range(2)])
    restart(trip_id)
    risk_sink.enqueue(trip_id, window(HIGH_RISK_WINDOW, index=2))

    async with bound_sink() as session:
        summary = await risk_sink.finalise_trip(trip_id, session=session)
        assert summary is not None
        assert summary.window_count == 3
        await session.rollback()
