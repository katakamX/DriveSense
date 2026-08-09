"""Liveness and readiness endpoints.

`/health` answers "is the process up?" and must never touch external systems.
`/health/ready` answers "can this instance serve traffic?" and therefore does
check the database. Container orchestrators need both signals distinctly: a
failing readiness check should remove an instance from rotation, while a
failing liveness check should restart it.
"""

import logging

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.session import get_db
from app.schemas.health import HealthResponse, ReadinessResponse

logger = logging.getLogger(__name__)

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    settings = get_settings()
    return HealthResponse(
        status="ok",
        service=settings.app_name,
        version=settings.version,
        environment=settings.environment,
    )


@router.get("/health/ready", response_model=ReadinessResponse)
async def readiness(response: Response, db: AsyncSession = Depends(get_db)) -> ReadinessResponse:
    database_ok = await _check_database(db)
    if not database_ok:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return ReadinessResponse(
        status="ready" if database_ok else "not_ready",
        database=database_ok,
    )


async def _check_database(db: AsyncSession) -> bool:
    try:
        await db.execute(text("SELECT 1"))
    except Exception:
        logger.warning("Database readiness check failed", exc_info=True)
        return False
    return True
