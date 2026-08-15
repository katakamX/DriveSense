"""Batched persistence for risk assessments. **The one impure module here.**

Everything else in `app.core.risk` is a pure function of its arguments. This
module holds process state and talks to PostgreSQL, and it lives in the risk
package anyway because that is where the pattern already is: `app.core.live.
broadcaster` and `app.core.events.state` are the same shape — module-level
per-trip state, created on first use, torn down by the application lifespan,
justified by the single-worker topology in ADR 0003.

The boundary is enforced by direction, not by convention: `schema`, `rules`,
`score` and `aggregate` import nothing from this module, so the property tests
that make up M9's exit criterion never touch a database.

## Why batch at all, when the tick is already 1 Hz

One tick per second per trip is one INSERT per second per trip, which the
frequency budget calls "batched, ~1 Hz" and would not be. Accumulating five
assessments — or five seconds, whichever comes first — makes that phrase true
without adding latency anyone can perceive: a risk number reaches the browser
over the WebSocket the instant it is computed, and the database write is a
durability concern trailing behind it, not part of the live path.

The time bound matters as much as the row bound. Without it a trip that ends
after three ticks would hold three unwritten rows until something else
happened to it.

## Two session sources, deliberately

Periodic flushes open their own session: they run inside the tick's asyncio
task, which has no request to borrow one from. The *final* flush — the one at
trip end — takes the request's session as an argument instead, so the last
risk rows and the trip's summary columns land in the same transaction as the
trip's own status change. A trip cannot be marked completed with its risk
summary missing.

## The accumulator is memory, and memory does not survive a restart

`_accumulators` holds the running fold for every live trip, and a restart wipes
it. What it does *not* wipe is `risk_windows`, because every assessment reaches
that table within five rows or five seconds of being computed. So a trip that
spans a restart ends with an accumulator covering only the windows scored since
the process came back — and `finalise_trip` would stamp that partial verdict
into `trips.risk_score` as though it were the whole drive. Silently: a summary
over the last two minutes of a forty-minute trip is a perfectly plausible
number, and nothing about it says it is wrong.

`finalise_trip` therefore checks the accumulator against the row count before
trusting it, and folds the persisted rows instead when it comes up short. The
comparison, rather than an unconditional rebuild, is deliberate: on the normal
path memory holds full float precision while the table has rounded to
`Numeric(5, 2)`, and there is no reason to publish the rounded answer when the
exact one is right there. The DB is the fallback, not the default.
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.risk.aggregate import EMPTY, TripRiskAccumulator, TripRiskSummary, finalise, fold
from app.core.risk.schema import (
    FeatureContribution,
    Provenance,
    RiskAssessment,
    RiskBand,
)
from app.db.models import RiskWindow, Trip
from app.db.session import SessionLocal

logger = logging.getLogger(__name__)

# Five rows or five seconds, whichever comes first.
FLUSH_ROWS = 5
FLUSH_INTERVAL_S = 5.0

_pending: dict[uuid.UUID, list[RiskAssessment]] = {}
_accumulators: dict[uuid.UUID, TripRiskAccumulator] = {}
_last_flush_at: dict[uuid.UUID, float] = {}

# Overridable so tests can bind the sink to their own transaction-scoped
# session factory. A sink that always reached for the global factory would
# write outside the test's rollback and leave rows behind.
_session_factory: async_sessionmaker[AsyncSession] | None = None


def set_session_factory(factory: async_sessionmaker[AsyncSession] | None) -> None:
    global _session_factory
    _session_factory = factory


def _factory() -> async_sessionmaker[AsyncSession]:
    return _session_factory if _session_factory is not None else SessionLocal


def enqueue(trip_id: uuid.UUID, assessment: RiskAssessment) -> None:
    """Record one assessment. Never touches the database.

    Folding into the trip accumulator happens here rather than at flush time
    so that the running summary is correct even for assessments that have not
    been written yet, and so a flush failure cannot corrupt it.
    """
    _pending.setdefault(trip_id, []).append(assessment)
    _accumulators[trip_id] = fold(_accumulators.get(trip_id, EMPTY), assessment)
    _last_flush_at.setdefault(trip_id, time.monotonic())


def should_flush(trip_id: uuid.UUID, *, now: float | None = None) -> bool:
    pending = _pending.get(trip_id)
    if not pending:
        return False
    if len(pending) >= FLUSH_ROWS:
        return True
    started = _last_flush_at.get(trip_id)
    current = time.monotonic() if now is None else now
    return started is None or (current - started) >= FLUSH_INTERVAL_S


async def flush_if_due(trip_id: uuid.UUID) -> int:
    """Write the trip's pending rows if either bound has been reached.

    Returns the number of rows written. Called from the inference tick, which
    is why it is cheap when nothing is due.
    """
    if not should_flush(trip_id):
        return 0
    return await flush(trip_id)


async def flush(trip_id: uuid.UUID, *, session: AsyncSession | None = None) -> int:
    """Write every pending row for one trip. Returns how many.

    With `session`, joins the caller's transaction and leaves committing to
    them; without, opens and commits its own.
    """
    pending = _pending.pop(trip_id, [])
    _last_flush_at[trip_id] = time.monotonic()
    if not pending:
        return 0

    rows = [_to_row(trip_id, assessment) for assessment in pending]
    if session is not None:
        session.add_all(rows)
        await session.flush()
    else:
        async with _factory()() as owned:
            owned.add_all(rows)
            await owned.commit()
    return len(rows)


async def finalise_trip(
    trip_id: uuid.UUID, *, session: AsyncSession | None = None
) -> TripRiskSummary | None:
    """Flush the tail and stamp the trip's summary columns. For trip end.

    Returns `None` for a trip that never produced a window — a trip too short
    to score, which leaves the columns null rather than claiming a score of
    zero. Trip state is released either way: this is the last thing that
    happens to a trip in this process.

    Runs strictly after the tail flush, so by the time the accumulator is
    reconciled every window this process holds is already a row and the two
    are comparable.
    """
    await flush(trip_id, session=session)
    accumulator = _accumulators.pop(trip_id, None)
    _last_flush_at.pop(trip_id, None)
    _pending.pop(trip_id, None)

    if session is not None:
        return await _summarise_and_stamp(session, trip_id, accumulator)
    async with _factory()() as owned:
        summary = await _summarise_and_stamp(owned, trip_id, accumulator)
        await owned.commit()
        return summary


async def _summarise_and_stamp(
    session: AsyncSession, trip_id: uuid.UUID, accumulator: TripRiskAccumulator | None
) -> TripRiskSummary | None:
    reconciled = await _reconcile(session, trip_id, accumulator)
    if reconciled.window_count == 0:
        return None
    summary = finalise(reconciled)
    await _apply_summary(session, trip_id, summary)
    return summary


async def _reconcile(
    session: AsyncSession, trip_id: uuid.UUID, accumulator: TripRiskAccumulator | None
) -> TripRiskAccumulator:
    """The trip's true fold state: memory if it is complete, the table if not.

    "Complete" means the accumulator has folded at least as many windows as the
    table holds rows. It can legitimately hold *more* — `enqueue` folds before
    the row is written, and a flush that failed leaves the fold ahead of the
    table on purpose (see `enqueue`) — so the test is `>=`, not `==`.
    """
    persisted = await _persisted_window_count(session, trip_id)
    held = accumulator.window_count if accumulator is not None else 0
    if accumulator is not None and held >= persisted:
        return accumulator

    # Not a failure of this process, and usually not a failure at all: the
    # ordinary cause is a restart part-way through the trip. Logged at warning
    # because a summary rebuilt from rounded rows is not quite the summary the
    # live path would have produced, and that is worth being able to see.
    logger.warning(
        "Trip %s accumulator holds %d window(s) against %d persisted; "
        "rebuilding the summary from risk_windows",
        trip_id,
        held,
        persisted,
    )
    return await _rebuild_accumulator(session, trip_id)


async def _persisted_window_count(session: AsyncSession, trip_id: uuid.UUID) -> int:
    result = await session.execute(
        select(func.count()).select_from(RiskWindow).where(RiskWindow.trip_id == trip_id)
    )
    return int(result.scalar_one())


async def _rebuild_accumulator(session: AsyncSession, trip_id: uuid.UUID) -> TripRiskAccumulator:
    """Fold every persisted window for one trip, oldest first.

    Order is not required for correctness — every field of the accumulator is a
    sum, a count, a max or a min, which is what `test_risk_aggregate` asserts —
    but folding in window order costs nothing and keeps the rebuilt state
    identical to the one the live path would have built.
    """
    result = await session.execute(
        select(RiskWindow).where(RiskWindow.trip_id == trip_id).order_by(RiskWindow.window_end)
    )
    accumulator = EMPTY
    for row in result.scalars().all():
        accumulator = fold(accumulator, _from_row(row))
    return accumulator


async def _apply_summary(
    session: AsyncSession, trip_id: uuid.UUID, summary: TripRiskSummary
) -> None:
    trip = await session.get(Trip, trip_id)
    if trip is None:
        # The trip was deleted mid-flush. Nothing to stamp, and nothing wrong.
        return
    trip.risk_score = summary.trip_score
    trip.risk_band = summary.trip_band.value if summary.trip_band is not None else None
    trip.risk_engine_version = summary.risk_engine_version


def discard_trip(trip_id: uuid.UUID) -> None:
    """Drop all in-memory state for a trip without writing. For trip deletion."""
    _pending.pop(trip_id, None)
    _accumulators.pop(trip_id, None)
    _last_flush_at.pop(trip_id, None)


async def stop_all() -> None:
    """Write whatever is pending for every trip. For application shutdown.

    Deliberately does not stamp trip summaries: a trip that is still running
    when the process stops has not ended, and writing a final score for it
    would record a verdict on a drive that is still happening.
    """
    for trip_id in list(_pending):
        try:
            await flush(trip_id)
        except Exception:
            logger.exception("Failed to flush risk rows for trip %s at shutdown", trip_id)
    _pending.clear()
    _accumulators.clear()
    _last_flush_at.clear()


def pending_count(trip_id: uuid.UUID) -> int:
    """How many assessments are waiting to be written. For tests and diagnostics."""
    return len(_pending.get(trip_id, ()))


def accumulator_for(trip_id: uuid.UUID) -> TripRiskAccumulator | None:
    """The trip's running fold state, or `None` if it has none."""
    return _accumulators.get(trip_id)


def reset() -> None:
    """Drop every trip's state and unbind the session factory. For tests."""
    _pending.clear()
    _accumulators.clear()
    _last_flush_at.clear()
    set_session_factory(None)


def _to_row(trip_id: uuid.UUID, assessment: RiskAssessment) -> RiskWindow:
    contributions: list[dict[str, Any]] = [
        {
            "feature": contribution.feature,
            "value": contribution.value,
            "contribution": contribution.contribution,
        }
        for contribution in assessment.contributions
    ]
    return RiskWindow(
        trip_id=trip_id,
        window_start=assessment.window_start,
        window_end=assessment.window_end,
        sample_count=assessment.sample_count,
        coverage_ratio=assessment.coverage_ratio,
        score=assessment.score,
        band=assessment.band.value,
        confidence=assessment.confidence,
        provenance=assessment.provenance.value,
        model_available=assessment.model_available,
        gated=assessment.gated,
        rule_band=assessment.rule_band.value,
        matched_rules=list(assessment.matched_rules),
        model_band=assessment.model_band.value if assessment.model_band is not None else None,
        model_score=assessment.model_score,
        model_predicted_class=assessment.model_predicted_class,
        probabilities=dict(assessment.probabilities)
        if assessment.probabilities is not None
        else None,
        contributions=contributions or None,
        contributions_remainder=assessment.contributions_remainder,
        risk_engine_version=assessment.risk_engine_version,
        feature_version=assessment.feature_version,
        rubric_version=assessment.rubric_version,
        model_version=assessment.model_version,
    )


def _from_row(row: RiskWindow) -> RiskAssessment:
    """Inverse of `_to_row`, to the precision the columns kept.

    Not a perfect round trip and cannot be: `score` is `Numeric(5, 2)` and
    `coverage_ratio` is `Numeric(4, 3)`, so a rebuilt assessment carries the
    stored value, not the computed one. That is the whole cost of recovering a
    summary from the table, and it is bounded by the column definitions.
    """
    contributions = tuple(
        FeatureContribution(
            feature=str(entry["feature"]),
            value=float(entry["value"]),
            contribution=float(entry["contribution"]),
        )
        for entry in (row.contributions or ())
    )
    return RiskAssessment(
        risk_engine_version=row.risk_engine_version,
        feature_version=row.feature_version,
        rubric_version=row.rubric_version,
        model_version=row.model_version,
        window_start=row.window_start,
        window_end=row.window_end,
        sample_count=row.sample_count,
        coverage_ratio=float(row.coverage_ratio),
        score=float(row.score),
        band=RiskBand(row.band),
        confidence=float(row.confidence),
        provenance=Provenance(row.provenance),
        model_available=row.model_available,
        gated=row.gated,
        rule_band=RiskBand(row.rule_band),
        matched_rules=tuple(row.matched_rules),
        model_band=RiskBand(row.model_band) if row.model_band is not None else None,
        model_score=float(row.model_score) if row.model_score is not None else None,
        model_predicted_class=row.model_predicted_class,
        probabilities=dict(row.probabilities) if row.probabilities is not None else None,
        contributions=contributions,
        contributions_remainder=float(row.contributions_remainder or 0.0),
    )


__all__ = [
    "FLUSH_INTERVAL_S",
    "FLUSH_ROWS",
    "accumulator_for",
    "discard_trip",
    "enqueue",
    "finalise_trip",
    "flush",
    "flush_if_due",
    "pending_count",
    "reset",
    "set_session_factory",
    "should_flush",
    "stop_all",
]
