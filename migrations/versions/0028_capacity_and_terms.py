"""A cap on accounts per municipality, and proof of accepting the terms.

- ``towns.max_residents``: how many accounts a municipality admits. Null
  means no limit, which is what every municipality has until someone sets
  one (the pilot uses 200).
- ``users.terms_accepted_at`` / ``users.terms_version``: when a person
  accepted the pilot terms and which version. Null for accounts created
  before the terms existed.

Additive only: three nullable columns, no backfill, no index. A database
with data and a freshly created one end up the same, and the API that was
running before this revision keeps working with the columns there.

Revision ID: 0028_capacity_and_terms
Revises: 0027_reward_catalog
Create Date: 2026-11-27
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0028_capacity_and_terms"
down_revision: Union[str, None] = "0027_reward_catalog"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

COLUMNS: tuple[tuple[str, sa.Column], ...] = (
    ("towns", sa.Column("max_residents", sa.Integer(), nullable=True)),
    ("users", sa.Column("terms_accepted_at", sa.DateTime(), nullable=True)),
    ("users", sa.Column("terms_version", sa.String(16), nullable=True)),
)


def _has(table: str, column: str) -> bool:
    insp = sa.inspect(op.get_bind())
    return any(c["name"] == column for c in insp.get_columns(table))


def upgrade() -> None:
    """Each step checks whether it is already done (MySQL has no DDL rollback)."""
    for table, column in COLUMNS:
        if not _has(table, column.name):
            op.add_column(table, column.copy())


def downgrade() -> None:
    for table, column in reversed(COLUMNS):
        if _has(table, column.name):
            op.drop_column(table, column.name)
