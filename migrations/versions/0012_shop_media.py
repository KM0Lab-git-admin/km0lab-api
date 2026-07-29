"""Store shop logo/hero as LONGBLOB in shop_media

Revision ID: 0012_shop_media
Revises: 0011_shop_categories
Create Date: 2026-07-28
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.mysql import LONGBLOB

revision: str = "0012_shop_media"
down_revision: Union[str, None] = "0011_shop_categories"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "shop_media",
        sa.Column("id", sa.String(length=32), primary_key=True),
        sa.Column("shop_id", sa.String(length=32), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("content_type", sa.String(length=64), nullable=False),
        sa.Column("data", LONGBLOB(), nullable=False),
        sa.Column("byte_size", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["shop_id"], ["shops.id"], ondelete="CASCADE"
        ),
        sa.UniqueConstraint("shop_id", "kind", name="uq_shop_media_kind"),
    )
    op.create_index("ix_shop_media_shop_id", "shop_media", ["shop_id"])


def downgrade() -> None:
    op.drop_index("ix_shop_media_shop_id", table_name="shop_media")
    op.drop_table("shop_media")
