"""driver_code_and_current_vehicle

Revision ID: 3750a6b03f0b
Revises: f4d908e54271
Create Date: 2026-08-16 11:13:14.483922

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "3750a6b03f0b"
down_revision: str | Sequence[str] | None = "f4d908e54271"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("drivers", sa.Column("driver_code", sa.String(length=64), nullable=True))
    op.add_column("drivers", sa.Column("current_vehicle_id", sa.Uuid(), nullable=True))
    op.create_unique_constraint(
        op.f("uq_drivers_driver_code"), "drivers", ["driver_code"]
    )
    op.create_foreign_key(
        op.f("fk_drivers_current_vehicle_id_vehicles"),
        "drivers",
        "vehicles",
        ["current_vehicle_id"],
        ["id"],
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint(
        op.f("fk_drivers_current_vehicle_id_vehicles"), "drivers", type_="foreignkey"
    )
    op.drop_constraint(op.f("uq_drivers_driver_code"), "drivers", type_="unique")
    op.drop_column("drivers", "current_vehicle_id")
    op.drop_column("drivers", "driver_code")
