"""points_transactions + qr_scans + redemptions + redemption_events

Revision ID: 0006_ledger_scans_redemptions
Revises: 0005_point_actions_rewards
Create Date: 2026-07-28
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0006_ledger_scans_redemptions"
down_revision: Union[str, None] = "0005_point_actions_rewards"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "points_transactions",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("user_id", sa.String(length=32), nullable=False),
        sa.Column("town_id", sa.String(length=32), nullable=True),
        sa.Column("type", sa.String(length=30), nullable=False),
        sa.Column("points", sa.Integer(), nullable=False),
        sa.Column("ref_id", sa.String(length=32), nullable=True),
        sa.Column("description", sa.String(length=255), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["town_id"], ["towns.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_points_transactions_user_id", "points_transactions", ["user_id"])
    op.create_index("ix_points_transactions_town_id", "points_transactions", ["town_id"])
    op.create_index("ix_points_transactions_ref_id", "points_transactions", ["ref_id"])
    op.create_index(
        "ix_points_transactions_created_at", "points_transactions", ["created_at"]
    )

    op.create_table(
        "qr_scans",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("user_id", sa.String(length=32), nullable=False),
        sa.Column("shop_id", sa.String(length=32), nullable=False),
        sa.Column("points", sa.Integer(), nullable=False),
        sa.Column("scan_date", sa.Date(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["shop_id"], ["shops.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id", "shop_id", "scan_date", name="uq_qr_scan_user_shop_day"
        ),
    )
    op.create_index("ix_qr_scans_user_id", "qr_scans", ["user_id"])
    op.create_index("ix_qr_scans_shop_id", "qr_scans", ["shop_id"])
    op.create_index("ix_qr_scans_scan_date", "qr_scans", ["scan_date"])

    op.create_table(
        "redemptions",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("town_id", sa.String(length=32), nullable=False),
        sa.Column("user_id", sa.String(length=32), nullable=False),
        sa.Column("reward_id", sa.String(length=32), nullable=False),
        sa.Column("flow", sa.String(length=20), nullable=False),
        sa.Column("points_spent", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("amount", sa.String(length=80), nullable=True),
        sa.Column("shop_id", sa.String(length=32), nullable=True),
        sa.Column("used_at", sa.DateTime(), nullable=True),
        sa.Column("amount_applied", sa.String(length=80), nullable=True),
        sa.Column("delivered_at", sa.DateTime(), nullable=True),
        sa.Column(
            "requested_at", sa.DateTime(), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["town_id"], ["towns.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["reward_id"], ["rewards.id"]),
        sa.ForeignKeyConstraint(["shop_id"], ["shops.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_redemptions_town_id", "redemptions", ["town_id"])
    op.create_index("ix_redemptions_user_id", "redemptions", ["user_id"])
    op.create_index("ix_redemptions_reward_id", "redemptions", ["reward_id"])
    op.create_index("ix_redemptions_status", "redemptions", ["status"])

    op.create_table(
        "redemption_events",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("redemption_id", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("note", sa.String(length=255), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["redemption_id"], ["redemptions.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_redemption_events_redemption_id", "redemption_events", ["redemption_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_redemption_events_redemption_id", table_name="redemption_events")
    op.drop_table("redemption_events")
    op.drop_index("ix_redemptions_status", table_name="redemptions")
    op.drop_index("ix_redemptions_reward_id", table_name="redemptions")
    op.drop_index("ix_redemptions_user_id", table_name="redemptions")
    op.drop_index("ix_redemptions_town_id", table_name="redemptions")
    op.drop_table("redemptions")
    op.drop_index("ix_qr_scans_scan_date", table_name="qr_scans")
    op.drop_index("ix_qr_scans_shop_id", table_name="qr_scans")
    op.drop_index("ix_qr_scans_user_id", table_name="qr_scans")
    op.drop_table("qr_scans")
    op.drop_index("ix_points_transactions_created_at", table_name="points_transactions")
    op.drop_index("ix_points_transactions_ref_id", table_name="points_transactions")
    op.drop_index("ix_points_transactions_town_id", table_name="points_transactions")
    op.drop_index("ix_points_transactions_user_id", table_name="points_transactions")
    op.drop_table("points_transactions")
