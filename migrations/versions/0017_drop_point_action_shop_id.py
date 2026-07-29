"""drop point_actions.shop_id

Revision ID: 0017_drop_point_action_shop_id
Revises: 0016_qr_cooldown
Create Date: 2026-07-29
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0017_drop_point_action_shop_id"
down_revision: Union[str, None] = "0016_qr_cooldown"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    fks = conn.execute(
        sa.text(
            """
            SELECT CONSTRAINT_NAME
            FROM information_schema.KEY_COLUMN_USAGE
            WHERE TABLE_SCHEMA = DATABASE()
              AND TABLE_NAME = 'point_actions'
              AND COLUMN_NAME = 'shop_id'
              AND REFERENCED_TABLE_NAME IS NOT NULL
            """
        )
    ).fetchall()
    for (name,) in fks:
        op.execute(sa.text(f"ALTER TABLE point_actions DROP FOREIGN KEY `{name}`"))

    cols = conn.execute(
        sa.text(
            """
            SELECT COLUMN_NAME
            FROM information_schema.COLUMNS
            WHERE TABLE_SCHEMA = DATABASE()
              AND TABLE_NAME = 'point_actions'
              AND COLUMN_NAME = 'shop_id'
            """
        )
    ).fetchall()
    if cols:
        op.drop_column("point_actions", "shop_id")


def downgrade() -> None:
    op.add_column(
        "point_actions",
        sa.Column("shop_id", sa.String(length=32), nullable=True),
    )
    op.create_foreign_key(
        None,
        "point_actions",
        "shops",
        ["shop_id"],
        ["id"],
    )
