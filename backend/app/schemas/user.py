"""Request/response schemas for admin user/role management."""

from pydantic import BaseModel, field_validator

from app.db.models import UserRole


class UserRoleUpdate(BaseModel):
    role: str

    @field_validator("role")
    @classmethod
    def _valid_role(cls, value: str) -> str:
        if value not in set(UserRole):
            raise ValueError(f"role must be one of {sorted(UserRole)}")
        return value
