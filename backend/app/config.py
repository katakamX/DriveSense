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

    # Mailgun (app.core.mailgun), for OTP email on registration. Empty
    # defaults so a fresh checkout without `.env` still boots - sending is
    # skipped (with a log warning) rather than failing registration.
    mailgun_api_key: str = ""
    mailgun_domain: str = ""

    # Google OAuth (M-Auth-2, app.core.oauth). Empty defaults so a fresh
    # checkout without `.env` still boots - the /google/* routes just fail
    # until real credentials are configured, same posture as Mailgun above.
    google_client_id: str = ""
    google_client_secret: str = ""
    # Must exactly match a redirect URI registered in Google Cloud Console.
    google_redirect_uri: str = "http://localhost:8000/api/v1/auth/google/callback"
    # Signs the short-lived (state-only) session cookie Authlib uses to carry
    # its CSRF `state` value from /google/login to /google/callback. Distinct
    # from `session_cookie_name` above: that one is the app's own long-lived
    # login session, this one never outlives a single OAuth round trip.
    oauth_state_secret_key: str = "dev-oauth-state-secret-change-in-production"
    # Frontend route to land on once the callback has set the login cookie.
    oauth_success_redirect: str = "http://localhost:5173/"

    # Driver-application documents (M-Auth-3, app.core.documents). Local disk,
    # not object storage — see ADR 0009. Gitignored, and a container needs this
    # mounted as a volume for uploads to survive a restart.
    document_storage_dir: Path = REPO_ROOT / "storage" / "documents"
    # Per-file ceiling. Generous for a phone photo or a scanned PDF, small
    # enough that 13 of them per applicant stays unremarkable on disk.
    document_max_bytes: int = 10 * 1024 * 1024

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

    # `app.db.seed_admin` (`python -m app.db.seed_admin`). Dev-only login so
    # the admin role doesn't require a manual DB promotion after registering.
    # Change these in `.env` for anything other than a local checkout.
    seed_admin_email: str = "admin@drivesense.dev"
    seed_admin_password: str = "ChangeMe123!"


@lru_cache
def get_settings() -> Settings:
    """Cached settings accessor, safe to use as a FastAPI dependency."""
    return Settings()
