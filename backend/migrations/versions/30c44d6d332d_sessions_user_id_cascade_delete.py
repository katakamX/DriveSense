"""sessions user_id cascade delete

Revision ID: 30c44d6d332d
Revises: a1b2c3d4e5f6
Create Date: 2026-08-16 21:24:04.639347

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "30c44d6d332d"
down_revision: str | Sequence[str] | None = "a1b2c3d4e5f6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.drop_constraint(op.f("fk_sessions_user_id_users"), "sessions", type_="foreignkey")
    op.create_foreign_key(
        op.f("fk_sessions_user_id_users"),
        "sessions",
        "users",
        ["user_id"],
        ["id"],
        ondelete="CASCADE",
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint(op.f("fk_sessions_user_id_users"), "sessions", type_="foreignkey")
    op.create_foreign_key(
        op.f("fk_sessions_user_id_users"), "sessions", "users", ["user_id"], ["id"]
    )
