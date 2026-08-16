"""Application configuration, loaded from the environment.

Secrets never live in source. Local development reads the repository `.env`
file (see `.env.example`); containers receive values from Docker Compose.
"""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=("../.env", ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "DriveSense API"
    version: str = "0.1.0"
    environment: str = "development"
    log_level: str = "INFO"

    api_prefix: str = "/api/v1"

    database_url: str = "postgresql+psycopg://drivesense:drivesense@localhost:5432/drivesense"

    # Auth (M-Auth-1). Sessions are DB-backed, cookie-carried opaque tokens,
    # not JWT - simplest correct choice for one frontend talking to one
    # backend, with instant server-side revocation (logout deletes the row).
    session_cookie_name: str = "ds_session"
    session_ttl_hours: int = 24 * 14
    # `Secure` requires HTTPS; the Vite dev server is plain HTTP, so this
    # follows `environment` rather than being hardcoded True.
    session_cookie_secure: bool = False

    # Fallback speed limit for trips that don't set their own — a configured
    # placeholder, not a claim about any real road's actual limit.
    default_speed_limit_kph: float = 100.0

    # Trained model artefact. `ml/artifacts/` is gitignored, so a fresh
    # checkout has none and the backend comes up rule-only — a supported
    # state, not a failure (see app/ml/loader.py).
    model_path: Path = REPO_ROOT / "ml" / "artifacts" / "model.json"

    # Nominal producer frame rate. Used only to turn a window's sample count
    # into a coverage ratio; never inferred from the data, because a gap in
    # the data is exactly what coverage_ratio has to be able to detect
    # (same contract as `make_windows(expected_rate_hz=...)`).
    telemetry_rate_hz: float = 10.0

    # Origins allowed to call the API from a browser. The Vite dev server
    # proxies /api, so this matters mainly for direct cross-origin access.
    cors_origins: list[str] = ["http://localhost:5173", "http://localhost:3000"]


@lru_cache
def get_settings() -> Settings:
    """Cached settings accessor, safe to use as a FastAPI dependency."""
    return Settings()
