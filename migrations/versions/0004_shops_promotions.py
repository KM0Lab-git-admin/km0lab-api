"""shops + promotions + users.shop_id

Revision ID: 0004_shops_promotions
Revises: 0003_towns_roles
Create Date: 2026-07-28
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0004_shops_promotions"
down_revision: Union[str, None] = "0003_towns_roles"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "shops",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("town_id", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("emoji", sa.String(length=16), nullable=True),
        sa.Column("logo_url", sa.String(length=512), nullable=True),
        sa.Column("hero_url", sa.String(length=512), nullable=True),
        sa.Column("categories", sa.JSON(), nullable=False),
        sa.Column("contact_email", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("visit_points", sa.Integer(), nullable=False, server_default="10"),
        sa.Column("address", sa.String(length=255), nullable=True),
        sa.Column("postal_code", sa.String(length=10), nullable=True),
        sa.Column("phone", sa.String(length=40), nullable=True),
        sa.Column("website", sa.String(length=255), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("opening_hours", sa.JSON(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="pending"),
        sa.Column("qr_code", sa.String(length=64), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["town_id"], ["towns.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("qr_code"),
    )
    op.create_index("ix_shops_town_id", "shops", ["town_id"])
    op.create_index("ix_shops_status", "shops", ["status"])
    op.create_index("ix_shops_qr_code", "shops", ["qr_code"])

    op.create_table(
        "promotions",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("shop_id", sa.String(length=32), nullable=False),
        sa.Column("type", sa.String(length=30), nullable=False),
        sa.Column("label", sa.String(length=80), nullable=False, server_default=""),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("detail", sa.Text(), nullable=False),
        sa.Column("value", sa.String(length=80), nullable=True),
        sa.Column("min_purchase", sa.String(length=80), nullable=True),
        sa.Column("valid_from", sa.DateTime(), nullable=True),
        sa.Column("valid_until", sa.DateTime(), nullable=True),
        sa.Column("conditions", sa.Text(), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["shop_id"], ["shops.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_promotions_shop_id", "promotions", ["shop_id"])

    op.add_column("users", sa.Column("shop_id", sa.String(length=32), nullable=True))
    op.create_index("ix_users_shop_id", "users", ["shop_id"])
    op.create_foreign_key("fk_users_shop_id", "users", "shops", ["shop_id"], ["id"])


def downgrade() -> None:
    op.drop_constraint("fk_users_shop_id", "users", type_="foreignkey")
    op.drop_index("ix_users_shop_id", table_name="users")
    op.drop_column("users", "shop_id")
    op.drop_index("ix_promotions_shop_id", table_name="promotions")
    op.drop_table("promotions")
    op.drop_index("ix_shops_qr_code", table_name="shops")
    op.drop_index("ix_shops_status", table_name="shops")
    op.drop_index("ix_shops_town_id", table_name="shops")
    op.drop_table("shops")
