"""driver status + document uploads

Revision ID: b7e2f1a94c30
Revises: 30c44d6d332d
Create Date: 2026-08-17 09:10:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b7e2f1a94c30"
down_revision: str | Sequence[str] | None = "30c44d6d332d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("drivers", sa.Column("user_id", sa.Uuid(), nullable=True))
    op.create_unique_constraint("uq_drivers_user_id", "drivers", ["user_id"])
    op.create_foreign_key(
        "fk_drivers_user_id_users", "drivers", "users", ["user_id"], ["id"], ondelete="SET NULL"
    )

    # Backfilled as "verified", not the ORM's "draft" default for new rows:
    # every driver predating this column was created directly through the
    # staff-only `/drivers` endpoints and is already an active, monitored
    # driver — there is no application for anyone to review. The server
    # default is dropped afterwards so new rows take `DriverStatus.DRAFT`
    # from the model instead.
    op.add_column(
        "drivers",
        sa.Column(
            "status", sa.String(length=20), nullable=False, server_default=sa.text("'verified'")
        ),
    )
    op.alter_column("drivers", "status", server_default=None)

    op.create_table(
        "document_uploads",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("driver_id", sa.Uuid(), nullable=False),
        sa.Column("document_type", sa.String(length=40), nullable=False),
        sa.Column("file_path", sa.String(length=500), nullable=False),
        sa.Column("content_type", sa.String(length=100), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column(
            "uploaded_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["driver_id"], ["drivers.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_document_uploads_driver_id"), "document_uploads", ["driver_id"], unique=False
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f("ix_document_uploads_driver_id"), table_name="document_uploads")
    op.drop_table("document_uploads")
    op.drop_column("drivers", "status")
    op.drop_constraint("fk_drivers_user_id_users", "drivers", type_="foreignkey")
    op.drop_constraint("uq_drivers_user_id", "drivers", type_="unique")
    op.drop_column("drivers", "user_id")
