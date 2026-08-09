"""Liveness and readiness endpoints.

`/health` answers "is the process up?" and must never touch external systems.
`/health/ready` answers "can this instance serve traffic?" and therefore does
check the database. Container orchestrators need both signals distinctly: a
failing readiness check should remove an instance from rotation, while a
failing liveness check should restart it.
"""

import logging

from fastapi import APIRouter, Response, status
from sqlalchemy import text

from app.config import get_settings
from app.db.session import get_engine
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
async def readiness(response: Response) -> ReadinessResponse:
    database_ok = await _check_database()
    if not database_ok:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return ReadinessResponse(
        status="ready" if database_ok else "not_ready",
        database=database_ok,
    )


async def _check_database() -> bool:
    try:
        async with get_engine().connect() as connection:
            await connection.execute(text("SELECT 1"))
    except Exception:
        logger.warning("Database readiness check failed", exc_info=True)
        return False
    return True
