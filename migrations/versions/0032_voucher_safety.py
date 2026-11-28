"""Safer vouchers: who validated, self-use, expiry, missed guesses.

Additive. Existing vouchers keep a null expiry (they do not expire), were
not self-validated, and have no validator until the next use. The API that
was running before ignores the new columns.

Revision ID: 0032_voucher_safety
Revises: 0031_session_epoch
Create Date: 2026-11-28
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0032_voucher_safety"
down_revision: Union[str, None] = "0031_session_epoch"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

REDEMPTIONS = "redemptions"
ATTEMPTS = "voucher_attempts"


def _columns(table: str) -> set[str]:
    insp = sa.inspect(op.get_bind())
    if not insp.has_table(table):
        return set()
    return {c["name"] for c in insp.get_columns(table)}


def upgrade() -> None:
    """Checks whether it is already done (MySQL has no DDL rollback)."""
    present = _columns(REDEMPTIONS)
    if "validated_by_user_id" not in present:
        op.add_column(
            REDEMPTIONS,
            sa.Column("validated_by_user_id", sa.String(length=32), nullable=True),
        )
        op.create_foreign_key(
            "fk_redemptions_validated_by_user_id",
            REDEMPTIONS,
            "users",
            ["validated_by_user_id"],
            ["id"],
            ondelete="SET NULL",
        )
    if "self_validated" not in present:
        op.add_column(
            REDEMPTIONS,
            sa.Column(
                "self_validated",
                sa.Boolean(),
                nullable=False,
                server_default="0",
            ),
        )
    if "expires_at" not in present:
        op.add_column(
            REDEMPTIONS,
            sa.Column("expires_at", sa.DateTime(), nullable=True),
        )

    bind = op.get_bind()
    insp = sa.inspect(bind)
    if not insp.has_table(ATTEMPTS):
        op.create_table(
            ATTEMPTS,
            sa.Column("id", sa.String(length=32), primary_key=True),
            sa.Column("shop_id", sa.String(length=32), nullable=False),
            sa.Column("success", sa.Boolean(), nullable=False, server_default="0"),
            sa.Column(
                "attempted_at",
                sa.DateTime(),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.ForeignKeyConstraint(["shop_id"], ["shops.id"], ondelete="CASCADE"),
        )
    # MySQL keeps the shop index for the foreign key, so a failed downgrade
    # can leave the table without the time index. Recreate whatever is missing.
    fresh = sa.inspect(bind)
    fresh.clear_cache()
    names = {ix["name"] for ix in fresh.get_indexes(ATTEMPTS)}
    if "ix_voucher_attempts_shop_id" not in names:
        op.create_index("ix_voucher_attempts_shop_id", ATTEMPTS, ["shop_id"])
    if "ix_voucher_attempts_attempted_at" not in names:
        op.create_index("ix_voucher_attempts_attempted_at", ATTEMPTS, ["attempted_at"])


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    # drop_table removes the indexes. MySQL refuses to drop the shop index
    # on its own because the foreign key uses it.
    if insp.has_table(ATTEMPTS):
        op.drop_table(ATTEMPTS)
    present = _columns(REDEMPTIONS)
    if "expires_at" in present:
        op.drop_column(REDEMPTIONS, "expires_at")
    if "self_validated" in present:
        op.drop_column(REDEMPTIONS, "self_validated")
    if "validated_by_user_id" in present:
        fks = insp.get_foreign_keys(REDEMPTIONS)
        for fk in fks:
            if fk.get("constrained_columns") == ["validated_by_user_id"]:
                op.drop_constraint(fk["name"], REDEMPTIONS, type_="foreignkey")
        op.drop_column(REDEMPTIONS, "validated_by_user_id")
