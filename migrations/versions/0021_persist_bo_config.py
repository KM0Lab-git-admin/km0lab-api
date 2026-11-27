"""Persist BO config: visible_home, town rules, town_media

Revision ID: 0021_persist_bo_config
Revises: 0020_redemption_code
Create Date: 2026-07-29
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.mysql import LONGBLOB

revision: str = "0021_persist_bo_config"
down_revision: Union[str, None] = "0020_redemption_code"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "point_actions",
        sa.Column(
            "visible_home",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("1"),
        ),
    )
    op.create_index(
        "ix_point_actions_visible_home", "point_actions", ["visible_home"]
    )

    op.add_column(
        "towns",
        sa.Column(
            "points_per_euro",
            sa.Integer(),
            nullable=False,
            server_default="200",
        ),
    )
    op.add_column(
        "towns",
        sa.Column(
            "default_visit_points",
            sa.Integer(),
            nullable=False,
            server_default="10",
        ),
    )
    op.add_column(
        "towns",
        sa.Column(
            "default_lang",
            sa.String(length=5),
            nullable=False,
            server_default="ca",
        ),
    )

    op.create_table(
        "town_media",
        sa.Column("id", sa.String(length=32), primary_key=True),
        sa.Column("town_id", sa.String(length=32), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
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
            ["town_id"], ["towns.id"], ondelete="CASCADE"
        ),
        sa.UniqueConstraint("town_id", "kind", name="uq_town_media_kind"),
    )
    op.create_index("ix_town_media_town_id", "town_media", ["town_id"])


def downgrade() -> None:
    op.drop_index("ix_town_media_town_id", table_name="town_media")
    op.drop_table("town_media")
    op.drop_column("towns", "default_lang")
    op.drop_column("towns", "default_visit_points")
    op.drop_column("towns", "points_per_euro")
    op.drop_index("ix_point_actions_visible_home", table_name="point_actions")
    op.drop_column("point_actions", "visible_home")
