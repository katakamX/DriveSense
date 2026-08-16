"""normalize user role default

Revision ID: a1b2c3d4e5f6
Revises: ce080178e8a0
Create Date: 2026-08-16 18:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a1b2c3d4e5f6"
down_revision: str | Sequence[str] | None = "ce080178e8a0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """`role` now takes one of "user" / "employee" / "admin" (`app.db.models.user.UserRole`).

    The column predates the enum; the only value ever written was the ORM
    default "staff", which is not one of the three. Existing rows are
    normalized to "user" so they still round-trip through `UserRole`.
    """
    op.execute(sa.text("UPDATE users SET role = 'user' WHERE role = 'staff'"))


def downgrade() -> None:
    """No reverse mapping: "staff" carried no information "user" doesn't."""
