"""How each person gets into their account, and how the account was born.

- ``user_identities``: one row per way of getting in (the code sent by
  email, Google, Facebook, Apple). The one the account was born with is
  marked ``is_first``; that is "where this neighbour came from". Adding a
  provider later is a new value of ``provider``: no further migration.

Every account that exists today got in with the code sent to its email, so
each one gets a row ``email_code`` with its email, ``is_first`` and the
date the account was created. ``last_used_at`` stays empty: nobody knows
when they last came in.

Additive only: one new table. Nothing existing is touched, so the API that
was running before this revision keeps working. The backfill is plain
Python (the same on MySQL and SQLite) and can be run again: it only adds
the rows that are missing.

Revision ID: 0030_user_identities
Revises: 0029_shop_review_note
Create Date: 2026-11-28
"""

from __future__ import annotations

import uuid
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0030_user_identities"
down_revision: Union[str, None] = "0029_shop_review_note"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLE = "user_identities"
EMAIL_CODE = "email_code"
BATCH = 500


def _table() -> sa.Table:
    return sa.table(
        TABLE,
        sa.column("id", sa.String),
        sa.column("user_id", sa.String),
        sa.column("provider", sa.String),
        sa.column("subject", sa.String),
        sa.column("email", sa.String),
        sa.column("is_first", sa.Boolean),
        sa.column("created_at", sa.DateTime),
    )


def upgrade() -> None:
    """Each step checks whether it is already done (MySQL has no DDL rollback)."""
    bind = op.get_bind()
    if not sa.inspect(bind).has_table(TABLE):
        op.create_table(
            TABLE,
            sa.Column("id", sa.String(32), primary_key=True),
            sa.Column(
                "user_id",
                sa.String(32),
                sa.ForeignKey("users.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("provider", sa.String(20), nullable=False),
            sa.Column("subject", sa.String(255), nullable=False),
            sa.Column("email", sa.String(255), nullable=True),
            sa.Column(
                "is_first", sa.Boolean(), nullable=False, server_default=sa.false()
            ),
            sa.Column(
                "created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()
            ),
            sa.Column("last_used_at", sa.DateTime(), nullable=True),
            sa.UniqueConstraint(
                "provider", "subject", name="uq_user_identity_provider_subject"
            ),
        )
        op.create_index("ix_user_identities_user_id", TABLE, ["user_id"])

    # One "code by email" identity for every account that has none.
    identities = _table()
    users = sa.table(
        "users",
        sa.column("id", sa.String),
        sa.column("email", sa.String),
        sa.column("created_at", sa.DateTime),
    )
    have = {
        row[0] for row in bind.execute(sa.select(identities.c.user_id).distinct())
    }
    taken = {
        row[0]
        for row in bind.execute(
            sa.select(identities.c.subject).where(identities.c.provider == EMAIL_CODE)
        )
    }
    rows: list[dict] = []
    for user_id, email, created_at in bind.execute(
        sa.select(users.c.id, users.c.email, users.c.created_at)
    ):
        subject = (email or "").strip().lower()
        if user_id in have or not subject or subject in taken:
            continue
        taken.add(subject)
        rows.append(
            {
                "id": uuid.uuid4().hex,
                "user_id": user_id,
                "provider": EMAIL_CODE,
                "subject": subject,
                "email": email,
                "is_first": True,
                "created_at": created_at,
            }
        )
    for start in range(0, len(rows), BATCH):
        bind.execute(sa.insert(identities), rows[start : start + BATCH])


def downgrade() -> None:
    if sa.inspect(op.get_bind()).has_table(TABLE):
        op.drop_table(TABLE)
