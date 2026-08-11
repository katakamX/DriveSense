"""risk_windows + trip risk summary

Revision ID: 3c1b7a0d54e2
Revises: f9f283e16596
Create Date: 2026-08-11 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "3c1b7a0d54e2"
down_revision: str | Sequence[str] | None = "f9f283e16596"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "risk_windows",
        sa.Column("id", sa.BIGINT(), autoincrement=True, nullable=False),
        sa.Column("trip_id", sa.Uuid(), nullable=False),
        sa.Column("window_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("window_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sample_count", sa.Integer(), nullable=False),
        sa.Column("coverage_ratio", sa.Numeric(precision=4, scale=3), nullable=False),
        sa.Column("score", sa.Numeric(precision=5, scale=2), nullable=False),
        sa.Column("band", sa.String(length=20), nullable=False),
        sa.Column("confidence", sa.Numeric(precision=4, scale=3), nullable=False),
        sa.Column("provenance", sa.String(length=30), nullable=False),
        sa.Column("model_available", sa.Boolean(), nullable=False),
        sa.Column("gated", sa.Boolean(), nullable=False),
        sa.Column("rule_band", sa.String(length=20), nullable=False),
        sa.Column("matched_rules", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("model_band", sa.String(length=20), nullable=True),
        sa.Column("model_score", sa.Numeric(precision=5, scale=2), nullable=True),
        sa.Column("model_predicted_class", sa.String(length=20), nullable=True),
        sa.Column("probabilities", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("contributions", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("contributions_remainder", sa.Numeric(precision=12, scale=8), nullable=True),
        sa.Column("risk_engine_version", sa.String(length=20), nullable=False),
        sa.Column("feature_version", sa.String(length=20), nullable=False),
        sa.Column("rubric_version", sa.String(length=20), nullable=False),
        sa.Column("model_version", sa.String(length=64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["trip_id"], ["trips.id"], name=op.f("fk_risk_windows_trip_id_trips")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_risk_windows")),
    )
    op.create_index(
        "ix_risk_windows_trip_id_window_end",
        "risk_windows",
        ["trip_id", "window_end"],
        unique=False,
    )
    # Nullable: an in-progress trip has no final score, and a trip scored by
    # engine v1 must remain readable once v2 ships — which is what the third
    # column is for.
    op.add_column("trips", sa.Column("risk_score", sa.Numeric(precision=5, scale=2), nullable=True))
    op.add_column("trips", sa.Column("risk_band", sa.String(length=20), nullable=True))
    op.add_column("trips", sa.Column("risk_engine_version", sa.String(length=20), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("trips", "risk_engine_version")
    op.drop_column("trips", "risk_band")
    op.drop_column("trips", "risk_score")
    op.drop_index("ix_risk_windows_trip_id_window_end", table_name="risk_windows")
    op.drop_table("risk_windows")
