"""Response schema for the admin system-health endpoint."""

from pydantic import BaseModel


class SystemHealthResponse(BaseModel):
    risk_engine_version: str
    model_version: str | None
    model_loaded: bool
