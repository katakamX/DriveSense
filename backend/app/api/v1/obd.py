"""Upload an OBD2 CSV export and replay it as chunked, rules-only risk
assessments (see STEP4_FINDINGS.md and `app.core.obd`).

Synchronous, not a background job: the sample fixture (1780 rows, ~53s of
driving) parses and scores in well under a second, and `obd_upload_max_bytes`
caps the request at a size that stays fast — background-job infrastructure
would be solving a problem this endpoint doesn't have. Nothing is persisted;
the response *is* the analysis.
"""

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status

from app.config import get_settings
from app.core.deps import require_staff
from app.core.obd.features import DEFAULT_CHUNK_INTERVAL_S, build_replay
from app.core.obd.parse import ObdCsvError, parse_obd_csv
from app.schemas.obd import ObdAnalysisOut, ObdChunkOut
from app.schemas.risk import RiskOut

router = APIRouter(prefix="/obd", tags=["obd"], dependencies=[Depends(require_staff)])


@router.post("/analyze", response_model=ObdAnalysisOut)
async def analyze_obd(file: UploadFile = File(...)) -> ObdAnalysisOut:
    settings = get_settings()

    data = await file.read()
    if len(data) > settings.obd_upload_max_bytes:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"file exceeds the {settings.obd_upload_max_bytes} byte limit",
        )
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "file is not valid UTF-8 text") from exc

    try:
        rows = parse_obd_csv(text)
    except ObdCsvError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc

    chunks = build_replay(
        rows,
        base_time=datetime.now(UTC),
        speed_limit_kph=settings.default_speed_limit_kph,
    )

    return ObdAnalysisOut(
        row_count=len(rows),
        duration_s=chunks[-1].t,
        chunk_interval_s=DEFAULT_CHUNK_INTERVAL_S,
        chunks=[
            ObdChunkOut(
                t=chunk.t,
                speed_kmh=chunk.speed_kmh,
                rpm=chunk.rpm,
                gear=chunk.gear,
                throttle_pct=chunk.throttle_pct,
                brake_pct=chunk.brake_pct,
                risk=RiskOut.from_assessment(chunk.assessment) if chunk.assessment else None,
            )
            for chunk in chunks
        ],
    )
