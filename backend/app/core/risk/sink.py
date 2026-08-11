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
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.risk.aggregate import EMPTY, TripRiskAccumulator, TripRiskSummary, finalise, fold
from app.core.risk.schema import RiskAssessment
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
    """
    await flush(trip_id, session=session)
    accumulator = _accumulators.pop(trip_id, None)
    _last_flush_at.pop(trip_id, None)
    _pending.pop(trip_id, None)

    if accumulator is None or accumulator.window_count == 0:
        return None

    summary = finalise(accumulator)
    if session is not None:
        await _apply_summary(session, trip_id, summary)
    else:
        async with _factory()() as owned:
            await _apply_summary(owned, trip_id, summary)
            await owned.commit()
    return summary


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
