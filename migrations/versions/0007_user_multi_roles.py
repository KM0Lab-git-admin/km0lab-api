"""users: multi-role flags (resident / merchant / admin)

Revision ID: 0007_user_multi_roles
Revises: 0006_ledger_scans_redemptions
Create Date: 2026-07-28
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0007_user_multi_roles"
down_revision: Union[str, None] = "0006_ledger_scans_redemptions"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "is_resident",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
    )
    op.add_column(
        "users",
        sa.Column(
            "is_merchant",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.add_column(
        "users",
        sa.Column(
            "is_admin",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.create_index("ix_users_is_resident", "users", ["is_resident"])
    op.create_index("ix_users_is_merchant", "users", ["is_merchant"])
    op.create_index("ix_users_is_admin", "users", ["is_admin"])

    # Migrate legacy single role → flags. Merchants/admins also get resident
    # so they can use the app with the same email identity.
    conn = op.get_bind()
    conn.execute(
        sa.text(
            """
            UPDATE users SET
              is_resident = 1,
              is_merchant = CASE WHEN role = 'merchant' THEN 1 ELSE 0 END,
              is_admin = CASE WHEN role = 'admin' THEN 1 ELSE 0 END
            """
        )
    )

    op.drop_index("ix_users_role", table_name="users")
    op.drop_column("users", "role")


def downgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "role",
            sa.String(length=20),
            nullable=False,
            server_default="resident",
        ),
    )
    op.create_index("ix_users_role", "users", ["role"])
    conn = op.get_bind()
    conn.execute(
        sa.text(
            """
            UPDATE users SET role = CASE
              WHEN is_admin = 1 THEN 'admin'
              WHEN is_merchant = 1 THEN 'merchant'
              ELSE 'resident'
            END
            """
        )
    )
    op.drop_index("ix_users_is_admin", table_name="users")
    op.drop_index("ix_users_is_merchant", table_name="users")
    op.drop_index("ix_users_is_resident", table_name="users")
    op.drop_column("users", "is_admin")
    op.drop_column("users", "is_merchant")
    op.drop_column("users", "is_resident")
