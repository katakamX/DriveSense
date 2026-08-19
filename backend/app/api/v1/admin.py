"""Admin system-health endpoint (M12 page 7).

Current versions only — model version and risk engine version — not a
general health/errors dashboard (no audit log table exists yet to back
"recent errors"; descoped per M12_PLAN.md). Sourced from the live process
state (`app.ml.loader`, `RISK_ENGINE_VERSION`), not the latest `RiskWindow`
row: a fingerprint of the artefact actually loaded right now is the current
version regardless of whether any trip has been scored recently.
"""

from fastapi import APIRouter, Depends

from app.core.deps import require_admin
from app.core.risk.schema import RISK_ENGINE_VERSION
from app.ml.loader import model_fingerprint, model_is_loaded
from app.schemas.admin import SystemHealthResponse

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_admin)])


@router.get("/system-health", response_model=SystemHealthResponse)
async def system_health() -> SystemHealthResponse:
    return SystemHealthResponse(
        risk_engine_version=RISK_ENGINE_VERSION,
        model_version=model_fingerprint(),
        model_loaded=model_is_loaded(),
    )
