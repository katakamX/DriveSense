"""The batched writer: when it writes, what it writes, and what it refuses to.

Runs against a real PostgreSQL, inside a transaction that is rolled back, with
the sink bound to a session factory over that same connection — otherwise a
sink reaching for the global factory would commit outside the test's rollback
and leave rows behind.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.risk import RiskAssessment, assess
from app.core.risk import sink as risk_sink
from app.core.risk.schema import RiskBand
from app.db.models import Driver, RiskWindow, Trip, Vehicle
from app.db.session import engine
from tests.fixtures.risk.regenerate import BASELINE, load_toy_model, model_output

START = datetime(2026, 8, 11, 12, 0, 0, tzinfo=UTC)

CALM_WINDOW = {"speed_cv": 0.02, "accel_std": 0.15, "lat_accel_std": 0.20}
HIGH_RISK_WINDOW = {"speeding_time_ratio": 0.6, "accel_min": -2.5}


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


async def make_trip(factory: async_sessionmaker[AsyncSession]) -> uuid.UUID:
    suffix = uuid.uuid4().hex[:8]
    async with factory() as session:
        driver = Driver(
            name="Sink Test", license_number=f"SINK-{suffix}", date_of_birth=date(1990, 1, 1)
        )
        vehicle = Vehicle(
            make="Test",
            model="Rig",
            year=2020,
            vin=f"VIN{suffix}".ljust(17, "0")[:17],
            license_plate=f"PL-{suffix}"[:20],
        )
        session.add_all([driver, vehicle])
        await session.flush()
        trip = Trip(
            driver_id=driver.id, vehicle_id=vehicle.id, started_at=START, speed_limit_kph=100.0
        )
        session.add(trip)
        await session.commit()
        return trip.id


def window(
    overrides: dict[str, float] | None = None,
    *,
    index: int = 0,
    coverage: float = 1.0,
    use_model: bool = False,
) -> RiskAssessment:
    features = {**BASELINE, **(overrides or {})}
    return assess(
        features=features,
        model_output=model_output(load_toy_model(), features) if use_model else None,
        window_start=START + timedelta(seconds=index),
        window_end=START + timedelta(seconds=index + 30),
        sample_count=int(300 * coverage),
        coverage_ratio=coverage,
        model_version="toyfixture01" if use_model else None,
    )


async def count_rows(factory: async_sessionmaker[AsyncSession], trip_id: uuid.UUID) -> int:
    async with factory() as session:
        result = await session.execute(
            select(RiskWindow).where(RiskWindow.trip_id == trip_id).order_by(RiskWindow.id)
        )
        return len(list(result.scalars().all()))


# --- batching ---------------------------------------------------------------


async def test_enqueue_writes_nothing_on_its_own(
    bound_sink: async_sessionmaker[AsyncSession],
) -> None:
    trip_id = await make_trip(bound_sink)
    risk_sink.enqueue(trip_id, window())
    assert risk_sink.pending_count(trip_id) == 1
    assert await count_rows(bound_sink, trip_id) == 0


async def test_the_row_bound_triggers_a_flush(
    bound_sink: async_sessionmaker[AsyncSession],
) -> None:
    """Four assessments wait; the fifth writes all five in one batch."""
    trip_id = await make_trip(bound_sink)

    for index in range(risk_sink.FLUSH_ROWS - 1):
        risk_sink.enqueue(trip_id, window(index=index))
        assert await risk_sink.flush_if_due(trip_id) == 0

    risk_sink.enqueue(trip_id, window(index=risk_sink.FLUSH_ROWS - 1))
    assert await risk_sink.flush_if_due(trip_id) == risk_sink.FLUSH_ROWS
    assert risk_sink.pending_count(trip_id) == 0
    assert await count_rows(bound_sink, trip_id) == risk_sink.FLUSH_ROWS


async def test_the_time_bound_triggers_a_flush(
    bound_sink: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A trip that ticks slowly must not hold rows indefinitely."""
    trip_id = await make_trip(bound_sink)
    risk_sink.enqueue(trip_id, window())
    assert risk_sink.should_flush(trip_id) is False

    clock = [1_000_000.0]
    monkeypatch.setattr(risk_sink.time, "monotonic", lambda: clock[0])
    clock[0] += risk_sink.FLUSH_INTERVAL_S + 1.0
    assert risk_sink.should_flush(trip_id) is True
    assert await risk_sink.flush_if_due(trip_id) == 1


async def test_flushing_an_empty_queue_is_a_no_op(
    bound_sink: async_sessionmaker[AsyncSession],
) -> None:
    trip_id = await make_trip(bound_sink)
    assert await risk_sink.flush(trip_id) == 0
    assert await risk_sink.flush_if_due(trip_id) == 0


# --- what lands in the row ---------------------------------------------------


async def test_a_written_row_carries_the_whole_assessment(
    bound_sink: async_sessionmaker[AsyncSession],
) -> None:
    trip_id = await make_trip(bound_sink)
    assessment = window({"speed_mean": 200.0}, use_model=True)
    risk_sink.enqueue(trip_id, assessment)
    await risk_sink.flush(trip_id)

    async with bound_sink() as session:
        row = (
            await session.execute(select(RiskWindow).where(RiskWindow.trip_id == trip_id))
        ).scalar_one()

    assert row.band == assessment.band.value
    assert row.rule_band == assessment.rule_band.value
    assert assessment.model_band is not None
    assert row.model_band == assessment.model_band.value
    assert row.provenance == assessment.provenance.value
    assert row.gated is assessment.gated
    assert row.model_available is True
    assert float(row.score) == pytest.approx(assessment.score, abs=0.005)
    assert float(row.confidence) == pytest.approx(assessment.confidence, abs=0.0005)
    assert row.matched_rules == list(assessment.matched_rules)
    assert row.probabilities is not None
    assert set(row.probabilities) == set(assessment.probabilities or {})
    assert row.contributions is not None
    assert len(row.contributions) == len(assessment.contributions)
    assert row.risk_engine_version == assessment.risk_engine_version
    assert row.rubric_version == assessment.rubric_version
    assert row.feature_version == assessment.feature_version
    assert row.model_version == "toyfixture01"


async def test_a_rule_only_row_stores_nulls_rather_than_placeholders(
    bound_sink: async_sessionmaker[AsyncSession],
) -> None:
    trip_id = await make_trip(bound_sink)
    risk_sink.enqueue(trip_id, window())
    await risk_sink.flush(trip_id)

    async with bound_sink() as session:
        row = (
            await session.execute(select(RiskWindow).where(RiskWindow.trip_id == trip_id))
        ).scalar_one()

    assert row.model_available is False
    assert row.model_band is None
    assert row.model_score is None
    assert row.model_predicted_class is None
    assert row.probabilities is None
    assert row.contributions is None
    assert row.model_version is None


# --- trip end -----------------------------------------------------------------


async def test_finalise_writes_the_tail_and_stamps_the_trip(
    bound_sink: async_sessionmaker[AsyncSession],
) -> None:
    trip_id = await make_trip(bound_sink)
    risk_sink.enqueue(trip_id, window(CALM_WINDOW, index=0))
    risk_sink.enqueue(trip_id, window(HIGH_RISK_WINDOW, index=1))

    summary = await risk_sink.finalise_trip(trip_id)
    assert summary is not None
    assert summary.window_count == 2
    assert summary.max_score == 100.0

    assert await count_rows(bound_sink, trip_id) == 2
    async with bound_sink() as session:
        trip = await session.get(Trip, trip_id)
        assert trip is not None
        assert trip.risk_score is not None
        assert float(trip.risk_score) == pytest.approx(summary.trip_score or 0.0, abs=0.005)
        assert trip.risk_band == (summary.trip_band.value if summary.trip_band else None)
        assert trip.risk_engine_version == summary.risk_engine_version


async def test_finalise_releases_all_state(
    bound_sink: async_sessionmaker[AsyncSession],
) -> None:
    trip_id = await make_trip(bound_sink)
    risk_sink.enqueue(trip_id, window())
    await risk_sink.finalise_trip(trip_id)
    assert risk_sink.pending_count(trip_id) == 0
    assert risk_sink.accumulator_for(trip_id) is None


async def test_a_trip_with_no_windows_gets_no_score(
    bound_sink: async_sessionmaker[AsyncSession],
) -> None:
    """A trip too short to score is not a calm trip; the columns stay null."""
    trip_id = await make_trip(bound_sink)
    assert await risk_sink.finalise_trip(trip_id) is None
    async with bound_sink() as session:
        trip = await session.get(Trip, trip_id)
        assert trip is not None
        assert trip.risk_score is None
        assert trip.risk_band is None
        assert trip.risk_engine_version is None


async def test_finalise_joins_a_caller_supplied_transaction(
    bound_sink: async_sessionmaker[AsyncSession],
) -> None:
    """The trip-end path passes the request's session so the write is atomic with it."""
    trip_id = await make_trip(bound_sink)
    risk_sink.enqueue(trip_id, window(HIGH_RISK_WINDOW))

    async with bound_sink() as session:
        await risk_sink.finalise_trip(trip_id, session=session)
        # Not yet committed by the sink — the caller owns that.
        trip = await session.get(Trip, trip_id)
        assert trip is not None
        assert trip.risk_band == RiskBand.HIGH_RISK.value
        await session.rollback()

    assert await count_rows(bound_sink, trip_id) == 0


# --- accumulation and teardown ------------------------------------------------


async def test_the_accumulator_advances_without_a_write(
    bound_sink: async_sessionmaker[AsyncSession],
) -> None:
    """Folding at enqueue time means a flush failure cannot corrupt the summary."""
    trip_id = await make_trip(bound_sink)
    risk_sink.enqueue(trip_id, window(CALM_WINDOW, index=0))
    risk_sink.enqueue(trip_id, window(HIGH_RISK_WINDOW, index=1))

    accumulator = risk_sink.accumulator_for(trip_id)
    assert accumulator is not None
    assert accumulator.window_count == 2
    assert accumulator.score_max == 100.0
    assert await count_rows(bound_sink, trip_id) == 0


async def test_discard_drops_state_without_writing(
    bound_sink: async_sessionmaker[AsyncSession],
) -> None:
    """Trip deletion: the pending rows point at a trip that is about to not exist."""
    trip_id = await make_trip(bound_sink)
    risk_sink.enqueue(trip_id, window())
    risk_sink.discard_trip(trip_id)

    assert risk_sink.pending_count(trip_id) == 0
    assert risk_sink.accumulator_for(trip_id) is None
    assert await risk_sink.flush(trip_id) == 0
    assert await count_rows(bound_sink, trip_id) == 0


async def test_stop_all_drains_without_stamping_summaries(
    bound_sink: async_sessionmaker[AsyncSession],
) -> None:
    """A trip still running at shutdown has not ended, so it gets no final verdict."""
    first = await make_trip(bound_sink)
    second = await make_trip(bound_sink)
    risk_sink.enqueue(first, window(CALM_WINDOW))
    risk_sink.enqueue(second, window(HIGH_RISK_WINDOW))

    await risk_sink.stop_all()

    assert await count_rows(bound_sink, first) == 1
    assert await count_rows(bound_sink, second) == 1
    async with bound_sink() as session:
        for trip_id in (first, second):
            trip = await session.get(Trip, trip_id)
            assert trip is not None
            assert trip.risk_score is None
