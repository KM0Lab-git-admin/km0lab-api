"""Rewards remember which catalog reward they are a copy of.

The reward catalog is edited once (the Demo KM0 partition) and copied to
every municipality. Until now a copy was matched to its original by name,
so renaming a catalog reward left the old copy behind and created a new
one. ``rewards.catalog_id`` keeps the link.

Additive only: one nullable column, no backfill. The first run of
``scripts/seed_real_rewards.py`` fills it for the copies it recognises by
name; rows it does not recognise stay untouched.

Revision ID: 0027_reward_catalog
Revises: 0026_localities
Create Date: 2026-11-20
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0027_reward_catalog"
down_revision: Union[str, None] = "0026_localities"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

INDEX = "ix_rewards_catalog_id"


def upgrade() -> None:
    """Each step checks whether it is already done (MySQL has no DDL rollback)."""
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if not any(c["name"] == "catalog_id" for c in insp.get_columns("rewards")):
        op.add_column(
            "rewards", sa.Column("catalog_id", sa.String(32), nullable=True)
        )
    insp = sa.inspect(bind)
    if not any(ix["name"] == INDEX for ix in insp.get_indexes("rewards")):
        op.create_index(INDEX, "rewards", ["catalog_id"])


def downgrade() -> None:
    op.drop_index(INDEX, table_name="rewards")
    op.drop_column("rewards", "catalog_id")
