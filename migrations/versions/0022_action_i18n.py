"""i18n labels for point actions (ca/es/en) + public catalog resolution.

Revision ID: 0022_action_i18n
Revises: 0021_persist_bo_config
Create Date: 2026-07-29
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0022_action_i18n"
down_revision: Union[str, None] = "0021_persist_bo_config"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "point_actions",
        sa.Column("name_i18n", sa.JSON(), nullable=True),
    )
    op.add_column(
        "point_actions",
        sa.Column("description_i18n", sa.JSON(), nullable=True),
    )
    # Backfill existing rows with their single-language text under "ca".
    op.execute(
        "UPDATE point_actions SET name_i18n = JSON_OBJECT('ca', name) "
        "WHERE name_i18n IS NULL"
    )
    op.execute(
        "UPDATE point_actions SET description_i18n = JSON_OBJECT('ca', description) "
        "WHERE description_i18n IS NULL"
    )


def downgrade() -> None:
    op.drop_column("point_actions", "description_i18n")
    op.drop_column("point_actions", "name_i18n")
