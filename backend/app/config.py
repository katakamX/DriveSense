"""Application configuration, loaded from the environment.

Secrets never live in source. Local development reads the repository `.env`
file (see `.env.example`); containers receive values from Docker Compose.
"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


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

    # Fallback speed limit for trips that don't set their own — a configured
    # placeholder, not a claim about any real road's actual limit.
    default_speed_limit_kph: float = 100.0

    # Origins allowed to call the API from a browser. The Vite dev server
    # proxies /api, so this matters mainly for direct cross-origin access.
    cors_origins: list[str] = ["http://localhost:5173", "http://localhost:3000"]


@lru_cache
def get_settings() -> Settings:
    """Cached settings accessor, safe to use as a FastAPI dependency."""
    return Settings()
