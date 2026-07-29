"""point_actions.cooldown_days + drop daily QR unique

Revision ID: 0016_qr_cooldown
Revises: 0015_birth_date
Create Date: 2026-07-29
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0016_qr_cooldown"
down_revision: Union[str, None] = "0015_birth_date"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "point_actions",
        sa.Column("cooldown_days", sa.Integer(), nullable=True),
    )
    # Cooldown is enforced in app from last successful scan; daily unique no longer fits.
    op.drop_constraint("uq_qr_scan_user_shop_day", "qr_scans", type_="unique")


def downgrade() -> None:
    op.create_unique_constraint(
        "uq_qr_scan_user_shop_day",
        "qr_scans",
        ["user_id", "shop_id", "scan_date"],
    )
    op.drop_column("point_actions", "cooldown_days")
