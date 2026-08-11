"""driver_states

Revision ID: f4d908e54271
Revises: 3c1b7a0d54e2
Create Date: 2026-08-11 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f4d908e54271"
down_revision: str | Sequence[str] | None = "3c1b7a0d54e2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "driver_states",
        sa.Column("id", sa.BIGINT(), autoincrement=True, nullable=False),
        sa.Column("trip_id", sa.Uuid(), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "ingested_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("schema_version", sa.String(length=10), nullable=False),
        sa.Column("face_detected", sa.Boolean(), nullable=False),
        sa.Column("calibrated", sa.Boolean(), nullable=False),
        sa.Column("drowsiness", sa.Float(), nullable=True),
        sa.Column("distraction", sa.Float(), nullable=True),
        sa.Column("perclos", sa.Float(), nullable=True),
        sa.Column("blink_rate_per_min", sa.Float(), nullable=True),
        sa.ForeignKeyConstraint(
            ["trip_id"], ["trips.id"], name=op.f("fk_driver_states_trip_id_trips")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_driver_states")),
    )
    op.create_index(
        "ix_driver_states_trip_id_recorded_at",
        "driver_states",
        ["trip_id", "recorded_at"],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_driver_states_trip_id_recorded_at", table_name="driver_states")
    op.drop_table("driver_states")
