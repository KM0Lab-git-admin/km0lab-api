"""shop_payments table + redemptions.payment_id

Revision ID: 0019_shop_payments
Revises: 0018_reward_media
Create Date: 2026-07-29
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0019_shop_payments"
down_revision: Union[str, None] = "0018_reward_media"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "shop_payments",
        sa.Column("id", sa.String(length=32), primary_key=True),
        sa.Column("town_id", sa.String(length=32), nullable=False),
        sa.Column("shop_id", sa.String(length=32), nullable=False),
        sa.Column("total_amount", sa.Numeric(10, 2), nullable=False),
        sa.Column("note", sa.String(length=255), nullable=True),
        sa.Column(
            "is_fake",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["town_id"], ["towns.id"]),
        sa.ForeignKeyConstraint(["shop_id"], ["shops.id"]),
    )
    op.create_index("ix_shop_payments_town_id", "shop_payments", ["town_id"])
    op.create_index("ix_shop_payments_shop_id", "shop_payments", ["shop_id"])
    op.create_index("ix_shop_payments_is_fake", "shop_payments", ["is_fake"])

    op.add_column(
        "redemptions",
        sa.Column("payment_id", sa.String(length=32), nullable=True),
    )
    op.create_index("ix_redemptions_payment_id", "redemptions", ["payment_id"])
    op.create_foreign_key(
        "fk_redemptions_payment_id",
        "redemptions",
        "shop_payments",
        ["payment_id"],
        ["id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_redemptions_payment_id", "redemptions", type_="foreignkey"
    )
    op.drop_index("ix_redemptions_payment_id", table_name="redemptions")
    op.drop_column("redemptions", "payment_id")
    op.drop_index("ix_shop_payments_is_fake", table_name="shop_payments")
    op.drop_index("ix_shop_payments_shop_id", table_name="shop_payments")
    op.drop_index("ix_shop_payments_town_id", table_name="shop_payments")
    op.drop_table("shop_payments")
