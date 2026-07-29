"""users.birth_date for birthday point actions

Revision ID: 0015_birth_date
Revises: 0014_slug_and_names
Create Date: 2026-07-29
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0015_birth_date"
down_revision: Union[str, None] = "0014_slug_and_names"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("birth_date", sa.Date(), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "birth_date")
