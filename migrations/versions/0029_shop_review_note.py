"""Why a shop's request to join was rejected.

- ``shops.review_note``: the reason the administrator wrote when rejecting
  a request. Until now it only travelled in the email; the shop has to be
  able to read it on its screen too. Null for every shop that was never
  rejected, and it goes with the request when it is deleted 30 days later.

Additive only: one nullable column, no backfill, no index. A database with
data and a freshly created one end up the same, and the API that was
running before this revision keeps working with the column there.

Revision ID: 0029_shop_review_note
Revises: 0028_capacity_and_terms
Create Date: 2026-11-28
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0029_shop_review_note"
down_revision: Union[str, None] = "0028_capacity_and_terms"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLE = "shops"
COLUMN = "review_note"


def _has() -> bool:
    insp = sa.inspect(op.get_bind())
    return any(c["name"] == COLUMN for c in insp.get_columns(TABLE))


def upgrade() -> None:
    """Checks whether it is already done (MySQL has no DDL rollback)."""
    if not _has():
        op.add_column(TABLE, sa.Column(COLUMN, sa.String(500), nullable=True))


def downgrade() -> None:
    if _has():
        op.drop_column(TABLE, COLUMN)
