"""Driver/vehicle/trip fixtures for a load-generator run.

`POST /trips` requires `require_staff`, and the load generator has no
interest in exercising staff auth -- that is a different endpoint's job, and
standing up a verified staff session just to create rows would test the auth
path, not the ingest -> browser path this benchmark measures. So this reaches
into the same database the backend itself uses and creates rows directly --
the same shortcut `backend/tests/conftest.py::register_staff` takes for its
own setup, applied here to trips instead of users.

Requires `drivesense-backend` importable (`pip install -e ../backend`), and
`DATABASE_URL` (or its default, matching `app.config.Settings`) reachable --
the same Postgres the backend itself is pointed at.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Driver, Trip, Vehicle

# Fixed, not one-per-run: `license_number`/`vin`/`license_plate` are unique
# columns, so a second run reuses the first run's rows instead of colliding
# with them.
BENCH_LICENSE_NUMBER = "BENCH-LOADGEN-0001"
BENCH_VIN = "BENCHLOADGEN0001"  # vehicles.vin is varchar(17)
BENCH_LICENSE_PLATE = "BENCH-LOADGEN-01"
DEFAULT_SPEED_LIMIT_KPH = 80.0


async def ensure_driver_and_vehicle(session: AsyncSession) -> tuple[uuid.UUID, uuid.UUID]:
    """Get-or-create the one driver/vehicle every bench trip attaches to."""
    driver = (
        await session.execute(select(Driver).where(Driver.license_number == BENCH_LICENSE_NUMBER))
    ).scalar_one_or_none()
    if driver is None:
        driver = Driver(
            name="Bench Load Generator",
            license_number=BENCH_LICENSE_NUMBER,
            date_of_birth=date(1990, 1, 1),
        )
        session.add(driver)

    vehicle = (
        await session.execute(select(Vehicle).where(Vehicle.vin == BENCH_VIN))
    ).scalar_one_or_none()
    if vehicle is None:
        vehicle = Vehicle(
            make="Bench",
            model="Load Generator",
            year=2026,
            vin=BENCH_VIN,
            license_plate=BENCH_LICENSE_PLATE,
        )
        session.add(vehicle)

    await session.commit()
    await session.refresh(driver)
    await session.refresh(vehicle)
    return driver.id, vehicle.id


async def create_trips(
    session: AsyncSession, driver_id: uuid.UUID, vehicle_id: uuid.UUID, count: int
) -> list[uuid.UUID]:
    """One fresh `in_progress` trip row per concurrent producer a level runs.

    Left behind after the run rather than cleaned up -- a benchmark trip is a
    real trip as far as the backend is concerned, and deleting it would also
    discard the telemetry/event rows it just cost a whole load-generator run
    to produce, which is exactly the data `docs/m14-benchmark.md` (step 6)
    would want to point back to.
    """
    trips = [
        Trip(
            driver_id=driver_id,
            vehicle_id=vehicle_id,
            started_at=datetime.now(UTC),
            status="in_progress",
            speed_limit_kph=DEFAULT_SPEED_LIMIT_KPH,
        )
        for _ in range(count)
    ]
    session.add_all(trips)
    await session.commit()
    for trip in trips:
        await session.refresh(trip)
    return [trip.id for trip in trips]
