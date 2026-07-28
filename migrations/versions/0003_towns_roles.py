"""towns + user role / town_id / phone / contact_shared

Revision ID: 0003_towns_roles
Revises: 0002_otp_attempts
Create Date: 2026-07-28
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0003_towns_roles"
down_revision: Union[str, None] = "0002_otp_attempts"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "towns",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("entity_name", sa.String(length=160), nullable=False, server_default=""),
        sa.Column(
            "entity_type", sa.String(length=20), nullable=False, server_default="city_council"
        ),
        sa.Column("contact_email", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("manager_name", sa.String(length=120), nullable=False, server_default=""),
        sa.Column("logo_url", sa.String(length=512), nullable=True),
        sa.Column("points_per_euro", sa.Integer(), nullable=False, server_default="200"),
        sa.Column("expiry_months", sa.Integer(), nullable=True),
        sa.Column(
            "default_visit_points", sa.Integer(), nullable=False, server_default="10"
        ),
        sa.Column("default_lang", sa.String(length=5), nullable=False, server_default="ca"),
        sa.Column(
            "created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    op.add_column(
        "users",
        sa.Column("role", sa.String(length=20), nullable=False, server_default="resident"),
    )
    op.add_column("users", sa.Column("town_id", sa.String(length=32), nullable=True))
    op.add_column("users", sa.Column("phone", sa.String(length=40), nullable=True))
    op.add_column(
        "users",
        sa.Column("contact_shared", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_index("ix_users_role", "users", ["role"])
    op.create_index("ix_users_town_id", "users", ["town_id"])
    op.create_foreign_key("fk_users_town_id", "users", "towns", ["town_id"], ["id"])


def downgrade() -> None:
    op.drop_constraint("fk_users_town_id", "users", type_="foreignkey")
    op.drop_index("ix_users_town_id", table_name="users")
    op.drop_index("ix_users_role", table_name="users")
    op.drop_column("users", "contact_shared")
    op.drop_column("users", "phone")
    op.drop_column("users", "town_id")
    op.drop_column("users", "role")
    op.drop_table("towns")
