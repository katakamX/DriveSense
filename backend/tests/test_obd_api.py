from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from tests.conftest import register_staff

FIXTURE = Path(__file__).parent / "fixtures" / "sample_obd.csv"


def _upload(client: TestClient, content: bytes, filename: str = "sample_obd.csv"):
    return client.post(
        "/api/v1/obd/analyze",
        files={"file": (filename, content, "text/csv")},
    )


@pytest.fixture(autouse=True)
async def _authenticated(client: TestClient, db_session: AsyncSession) -> None:
    await register_staff(client, db_session, "obd-tests@example.com")


def test_analyze_real_fixture(client: TestClient) -> None:
    response = _upload(client, FIXTURE.read_bytes())
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["row_count"] == 1780
    assert body["chunk_interval_s"] == 1.0
    assert len(body["chunks"]) > 40

    # Chunk times are strictly increasing and end at the file's last row.
    times = [c["t"] for c in body["chunks"]]
    assert times == sorted(times)
    assert times[-1] == pytest.approx(body["duration_s"])

    # Every chunk with a risk reading uses the OBD provenance vocabulary.
    with_risk = [c for c in body["chunks"] if c["risk"] is not None]
    assert with_risk
    for chunk in with_risk:
        risk = chunk["risk"]
        assert risk["provenance"] == "RULES_ONLY"
        assert risk["model_available"] is False
        assert risk["feature_version"] == "obd-1"
        for rule in risk["matched_rules"]:
            assert "lat_accel" not in rule


def test_missing_column_is_a_400(client: TestClient) -> None:
    response = _upload(client, b"Time_s,Speed_kmh\n0.03,0.0\n")
    assert response.status_code == 400
    assert "missing required column" in response.json()["detail"]


def test_non_utf8_file_is_a_400(client: TestClient) -> None:
    response = _upload(client, b"\xff\xfe\x00\x01not utf-8")
    assert response.status_code == 400


def test_oversized_file_is_a_400(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OBD_UPLOAD_MAX_BYTES", "10")
    get_settings.cache_clear()
    try:
        response = _upload(client, FIXTURE.read_bytes())
        assert response.status_code == 400
        assert "exceeds" in response.json()["detail"]
    finally:
        get_settings.cache_clear()
