"""Staff-side review of driver applications (M-Auth-4).

Every route here is gated on `require_staff` (employee or admin), not
`get_current_user` — this is the counterpart to `driver_applications.py`,
which is applicant-facing and only ever resolves `Driver.user_id ==
current_user.id`. Here the driver id comes from the path, since a reviewer
looks at applications that are not their own.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.driver_applications import build_application_read, load_documents
from app.core.deps import require_staff
from app.db.models import (
    REQUIRED_DOCUMENT_TOTAL,
    Driver,
    DocumentUpload,
)
from app.db.session import get_db
from app.schemas.driver_application import DriverApplicationRead, DriverApplicationSummary

router = APIRouter(
    prefix="/driver-review", tags=["driver-review"], dependencies=[Depends(require_staff)]
)


@router.get("/applications", response_model=list[DriverApplicationSummary])
async def list_applications(
    status_: str | None = Query(None, alias="status"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
) -> list[DriverApplicationSummary]:
    """The review queue. Unfiltered by default; `?status=pending` is the common case."""
    stmt = select(Driver)
    if status_ is not None:
        stmt = stmt.where(Driver.status == status_)
    stmt = stmt.order_by(Driver.created_at).limit(limit).offset(offset)
    result = await db.execute(stmt)
    drivers = list(result.scalars().all())

    counts: dict[uuid.UUID, int] = {}
    if drivers:
        driver_ids = [driver.id for driver in drivers]
        count_stmt = (
            select(DocumentUpload.driver_id, func.count())
            .where(DocumentUpload.driver_id.in_(driver_ids))
            .group_by(DocumentUpload.driver_id)
        )
        counts = dict((await db.execute(count_stmt)).all())

    return [
        DriverApplicationSummary(
            id=driver.id,
            name=driver.name,
            license_number=driver.license_number,
            status=driver.status,
            created_at=driver.created_at,
            documents_uploaded=min(counts.get(driver.id, 0), REQUIRED_DOCUMENT_TOTAL),
            documents_required=REQUIRED_DOCUMENT_TOTAL,
        )
        for driver in drivers
    ]


async def _load_driver(db: AsyncSession, driver_id: uuid.UUID) -> Driver:
    driver = await db.get(Driver, driver_id)
    if driver is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Driver application not found")
    return driver


@router.get("/applications/{driver_id}", response_model=DriverApplicationRead)
async def get_application(
    driver_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> DriverApplicationRead:
    driver = await _load_driver(db, driver_id)
    return build_application_read(driver, await load_documents(db, driver.id))
