"""redemptions.code — 5-digit merchant voucher code

Revision ID: 0020_redemption_code
Revises: 0019_shop_payments
Create Date: 2026-07-29
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0020_redemption_code"
down_revision: Union[str, None] = "0019_shop_payments"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "redemptions",
        sa.Column("code", sa.String(length=5), nullable=True),
    )
    op.create_index("uq_redemptions_code", "redemptions", ["code"], unique=True)


def downgrade() -> None:
    op.drop_index("uq_redemptions_code", table_name="redemptions")
    op.drop_column("redemptions", "code")
