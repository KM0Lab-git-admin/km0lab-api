"""reward_media LONGBLOB for catalog images

Revision ID: 0018_reward_media
Revises: 0017_drop_point_action_shop_id
Create Date: 2026-07-29
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.mysql import LONGBLOB

revision: str = "0018_reward_media"
down_revision: Union[str, None] = "0017_drop_point_action_shop_id"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "reward_media",
        sa.Column("id", sa.String(length=32), primary_key=True),
        sa.Column("reward_id", sa.String(length=32), nullable=False),
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
            ["reward_id"], ["rewards.id"], ondelete="CASCADE"
        ),
        sa.UniqueConstraint("reward_id", name="uq_reward_media_reward_id"),
    )
    op.create_index("ix_reward_media_reward_id", "reward_media", ["reward_id"])


def downgrade() -> None:
    op.drop_index("ix_reward_media_reward_id", table_name="reward_media")
    op.drop_table("reward_media")
