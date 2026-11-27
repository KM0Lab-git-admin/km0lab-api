"""Drop unused town config columns

Revision ID: 0009_drop_town_config_fields
Revises: 0008_town_postal_codes
Create Date: 2026-07-28
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0009_drop_town_config_fields"
down_revision: Union[str, None] = "0008_town_postal_codes"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_column("towns", "points_per_euro")
    op.drop_column("towns", "default_visit_points")
    op.drop_column("towns", "default_lang")


def downgrade() -> None:
    op.add_column(
        "towns",
        sa.Column(
            "default_lang",
            sa.String(length=5),
            nullable=False,
            server_default="ca",
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
            "points_per_euro",
            sa.Integer(),
            nullable=False,
            server_default="200",
        ),
    )
