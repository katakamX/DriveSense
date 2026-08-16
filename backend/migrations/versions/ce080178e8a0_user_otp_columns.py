"""user otp columns

Revision ID: ce080178e8a0
Revises: edb338d1ecff
Create Date: 2026-08-16 15:04:03.849637

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "ce080178e8a0"
down_revision: str | Sequence[str] | None = "edb338d1ecff"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("users", sa.Column("otp_code_hash", sa.String(length=64), nullable=True))
    op.add_column("users", sa.Column("otp_expires_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("users", "otp_expires_at")
    op.drop_column("users", "otp_code_hash")
