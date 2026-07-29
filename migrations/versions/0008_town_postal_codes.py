"""town_postal_codes + users.postal_code FK; drop users.town / users.town_id

Revision ID: 0008_town_postal_codes
Revises: 0007_user_multi_roles
Create Date: 2026-07-28
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0008_town_postal_codes"
down_revision: Union[str, None] = "0007_user_multi_roles"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "town_postal_codes",
        sa.Column("postal_code", sa.String(length=10), nullable=False),
        sa.Column("town_id", sa.String(length=32), nullable=False),
        sa.Column(
            "is_primary", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column(
            "created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["town_id"], ["towns.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("postal_code"),
    )
    op.create_index("ix_town_postal_codes_town_id", "town_postal_codes", ["town_id"])

    conn = op.get_bind()
    # Clear free-text postal codes that are not yet catalogued.
    conn.execute(sa.text("UPDATE users SET postal_code = NULL"))
    # One primary placeholder CP per existing town (seed can replace later).
    conn.execute(
        sa.text(
            """
            INSERT INTO town_postal_codes (postal_code, town_id, is_primary)
            SELECT CONCAT('T', SUBSTRING(id, 1, 9)), id, 1 FROM towns
            """
        )
    )
    # Point existing users at their town's primary CP.
    conn.execute(
        sa.text(
            """
            UPDATE users u
            INNER JOIN town_postal_codes tpc
              ON tpc.town_id = u.town_id AND tpc.is_primary = 1
            SET u.postal_code = tpc.postal_code
            WHERE u.town_id IS NOT NULL
            """
        )
    )

    op.drop_constraint("fk_users_town_id", "users", type_="foreignkey")
    op.drop_index("ix_users_town_id", table_name="users")
    op.drop_column("users", "town_id")
    op.drop_column("users", "town")

    op.create_foreign_key(
        "fk_users_postal_code",
        "users",
        "town_postal_codes",
        ["postal_code"],
        ["postal_code"],
    )


def downgrade() -> None:
    op.drop_constraint("fk_users_postal_code", "users", type_="foreignkey")
    op.add_column(
        "users",
        sa.Column("town", sa.String(length=120), nullable=True),
    )
    op.add_column(
        "users",
        sa.Column("town_id", sa.String(length=32), nullable=True),
    )
    conn = op.get_bind()
    conn.execute(
        sa.text(
            """
            UPDATE users u
            INNER JOIN town_postal_codes tpc ON tpc.postal_code = u.postal_code
            SET u.town_id = tpc.town_id
            """
        )
    )
    op.create_index("ix_users_town_id", "users", ["town_id"])
    op.create_foreign_key(
        "fk_users_town_id", "users", "towns", ["town_id"], ["id"]
    )
    op.drop_index("ix_town_postal_codes_town_id", table_name="town_postal_codes")
    op.drop_table("town_postal_codes")
