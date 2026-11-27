"""point_actions + rewards + reward_shops

Revision ID: 0005_point_actions_rewards
Revises: 0004_shops_promotions
Create Date: 2026-07-28
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0005_point_actions_rewards"
down_revision: Union[str, None] = "0004_shops_promotions"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "point_actions",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("town_id", sa.String(length=32), nullable=False),
        sa.Column("type", sa.String(length=30), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("points", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("per_user_limit", sa.Integer(), nullable=True),
        sa.Column("total_limit", sa.Integer(), nullable=True),
        sa.Column("valid_from", sa.DateTime(), nullable=True),
        sa.Column("valid_until", sa.DateTime(), nullable=True),
        sa.Column("conditions", sa.Text(), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("url", sa.String(length=512), nullable=True),
        sa.Column("event_id", sa.String(length=64), nullable=True),
        sa.Column("shop_id", sa.String(length=32), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["town_id"], ["towns.id"]),
        sa.ForeignKeyConstraint(["shop_id"], ["shops.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_point_actions_town_id", "point_actions", ["town_id"])

    op.create_table(
        "rewards",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("town_id", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("image_url", sa.String(length=512), nullable=True),
        sa.Column("type", sa.String(length=30), nullable=False),
        sa.Column("points_required", sa.Integer(), nullable=False),
        sa.Column("value", sa.String(length=80), nullable=True),
        sa.Column("stock", sa.Integer(), nullable=True),
        sa.Column("valid_from", sa.DateTime(), nullable=True),
        sa.Column("valid_until", sa.DateTime(), nullable=True),
        sa.Column("conditions", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="active"),
        sa.Column(
            "created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["town_id"], ["towns.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_rewards_town_id", "rewards", ["town_id"])
    op.create_index("ix_rewards_status", "rewards", ["status"])

    op.create_table(
        "reward_shops",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("reward_id", sa.String(length=32), nullable=False),
        sa.Column("shop_id", sa.String(length=32), nullable=False),
        sa.ForeignKeyConstraint(["reward_id"], ["rewards.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["shop_id"], ["shops.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("reward_id", "shop_id", name="uq_reward_shop"),
    )
    op.create_index("ix_reward_shops_reward_id", "reward_shops", ["reward_id"])
    op.create_index("ix_reward_shops_shop_id", "reward_shops", ["shop_id"])


def downgrade() -> None:
    op.drop_index("ix_reward_shops_shop_id", table_name="reward_shops")
    op.drop_index("ix_reward_shops_reward_id", table_name="reward_shops")
    op.drop_table("reward_shops")
    op.drop_index("ix_rewards_status", table_name="rewards")
    op.drop_index("ix_rewards_town_id", table_name="rewards")
    op.drop_table("rewards")
    op.drop_index("ix_point_actions_town_id", table_name="point_actions")
    op.drop_table("point_actions")
