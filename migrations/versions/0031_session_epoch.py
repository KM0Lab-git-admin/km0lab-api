"""Closing every session of an account from the server.

- ``users.session_epoch``: a counter. Every session token carries the value
  the account had when it was issued and is only valid while they match.
  "Close my session on all my devices" (or a lost phone) adds one, and
  every token issued before stops working.

A person signs in once and their session renews itself with use; this is
what still lets a session be cut. A counter rather than a date: nothing
depends on two clocks agreeing.

Additive only: one column, not null, default 0. Existing accounts get 0,
which is also what the tokens they already hold count as, so nobody is
signed out by this revision. The API that was running before keeps working
with the column there (it never writes it; the default fills it in).

Revision ID: 0031_session_epoch
Revises: 0030_user_identities
Create Date: 2026-11-28
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0031_session_epoch"
down_revision: Union[str, None] = "0030_user_identities"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLE = "users"
COLUMN = "session_epoch"


def _has() -> bool:
    insp = sa.inspect(op.get_bind())
    return any(c["name"] == COLUMN for c in insp.get_columns(TABLE))


def upgrade() -> None:
    """Checks whether it is already done (MySQL has no DDL rollback)."""
    if not _has():
        op.add_column(
            TABLE,
            sa.Column(COLUMN, sa.Integer(), nullable=False, server_default="0"),
        )


def downgrade() -> None:
    if _has():
        op.drop_column(TABLE, COLUMN)
