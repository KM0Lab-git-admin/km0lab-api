"""Invitation caps for people who were themselves invited.

``per_user_limit`` stays the cap for someone who joined alone (ring 0),
which is the number the backoffice already edits. Two new columns hold
the cap for ring 1 and ring 2. Null means "not set": the API then uses
the ring-0 number, so existing municipalities do not change until the
pilot script writes 3 / 1 / 0.

Additive. The API that was running before ignores the new columns.

Revision ID: 0033_invite_rings
Revises: 0032_voucher_safety
Create Date: 2026-11-28
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0033_invite_rings"
down_revision: Union[str, None] = "0032_voucher_safety"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLE = "point_actions"
COLUMNS = ("per_user_limit_ring1", "per_user_limit_ring2")


def _present() -> set[str]:
    insp = sa.inspect(op.get_bind())
    if not insp.has_table(TABLE):
        return set()
    return {c["name"] for c in insp.get_columns(TABLE)}


def upgrade() -> None:
    present = _present()
    for name in COLUMNS:
        if name not in present:
            op.add_column(TABLE, sa.Column(name, sa.Integer(), nullable=True))


def downgrade() -> None:
    present = _present()
    for name in reversed(COLUMNS):
        if name in present:
            op.drop_column(TABLE, name)
