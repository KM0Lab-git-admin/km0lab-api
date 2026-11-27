"""Add is_fake flag for demo content partition

Revision ID: 0010_is_fake
Revises: 0009_drop_town_config_fields
Create Date: 2026-07-28
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0010_is_fake"
down_revision: Union[str, None] = "0009_drop_town_config_fields"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLES = (
    "users",
    "shops",
    "promotions",
    "point_actions",
    "rewards",
    "points_transactions",
    "qr_scans",
    "redemptions",
    "redemption_events",
)


def upgrade() -> None:
    for table in _TABLES:
        op.add_column(
            table,
            sa.Column(
                "is_fake",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            ),
        )
        op.create_index(f"ix_{table}_is_fake", table, ["is_fake"])


def downgrade() -> None:
    for table in reversed(_TABLES):
        op.drop_index(f"ix_{table}_is_fake", table_name=table)
        op.drop_column(table, "is_fake")
