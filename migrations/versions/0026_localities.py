"""Localities: the towns (poblaciones) inside a municipality.

A ``towns`` row is the managed scope (the client): one admin, one set of
point rules, actions and rewards. Until now a postal code hung straight off
it, so a municipality grouping several towns could not tell them apart.

This adds the town below the municipality. Additive only:

- ``localities`` (name, slug, municipality) and ``locality_media`` (its
  illustration).
- ``town_postal_codes.locality_id`` and ``shops.locality_id`` (nullable).

Backfill: every existing municipality gets ONE locality with its own name
and slug, owning all its postal codes and shops. Nothing changes for them:
Malgrat stays Malgrat. Grouping towns is a data operation done later with
``scripts/group_towns.py``.

Revision ID: 0026_localities
Revises: 0025_invitations
Create Date: 2026-11-20
"""

from __future__ import annotations

import uuid
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "0026_localities"
down_revision: Union[str, None] = "0025_invitations"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_table(insp, name: str) -> bool:
    return name in insp.get_table_names()


def _has_column(insp, table: str, column: str) -> bool:
    return any(c["name"] == column for c in insp.get_columns(table))


def _has_index(insp, table: str, name: str) -> bool:
    return any(ix["name"] == name for ix in insp.get_indexes(table))


def _has_fk(insp, table: str, name: str) -> bool:
    return any(fk["name"] == name for fk in insp.get_foreign_keys(table))


def upgrade() -> None:
    """Every step checks first whether it is already done.

    MySQL does not roll back DDL: if this failed halfway on deploy, the
    tables created so far would stay and a plain retry would die on "table
    already exists". Written this way, running it again simply finishes.
    """
    bind = op.get_bind()

    if not _has_table(sa.inspect(bind), "localities"):
        op.create_table(
            "localities",
            sa.Column("id", sa.String(32), primary_key=True),
            sa.Column(
                "town_id",
                sa.String(32),
                sa.ForeignKey("towns.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("name", sa.String(120), nullable=False),
            sa.Column("slug", sa.String(80), nullable=False),
            sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime, server_default=sa.func.now()),
        )
    insp = sa.inspect(bind)
    if not _has_index(insp, "localities", "ix_localities_town_id"):
        op.create_index("ix_localities_town_id", "localities", ["town_id"])
    if not _has_index(insp, "localities", "ix_localities_slug"):
        op.create_index("ix_localities_slug", "localities", ["slug"], unique=True)

    if not _has_table(sa.inspect(bind), "locality_media"):
        op.create_table(
            "locality_media",
            sa.Column("id", sa.String(32), primary_key=True),
            sa.Column(
                "locality_id",
                sa.String(32),
                sa.ForeignKey("localities.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("kind", sa.String(20), nullable=False),
            sa.Column("content_type", sa.String(64), nullable=False),
            sa.Column(
                "data",
                sa.LargeBinary().with_variant(mysql.LONGBLOB(), "mysql"),
                nullable=False,
            ),
            sa.Column("byte_size", sa.Integer, nullable=False, server_default="0"),
            sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime, server_default=sa.func.now()),
            sa.UniqueConstraint(
                "locality_id", "kind", name="uq_locality_media_kind"
            ),
        )
    insp = sa.inspect(bind)
    if not _has_index(insp, "locality_media", "ix_locality_media_locality_id"):
        op.create_index(
            "ix_locality_media_locality_id", "locality_media", ["locality_id"]
        )

    for table, index, fk in (
        (
            "town_postal_codes",
            "ix_town_postal_codes_locality_id",
            "fk_town_postal_codes_locality",
        ),
        ("shops", "ix_shops_locality_id", "fk_shops_locality"),
    ):
        insp = sa.inspect(bind)
        if not _has_column(insp, table, "locality_id"):
            op.add_column(
                table, sa.Column("locality_id", sa.String(32), nullable=True)
            )
        insp = sa.inspect(bind)
        if not _has_index(insp, table, index):
            op.create_index(index, table, ["locality_id"])
        if not _has_fk(insp, table, fk):
            op.create_foreign_key(
                fk, table, "localities", ["locality_id"], ["id"], ondelete="SET NULL"
            )

    # ── Backfill: one locality per municipality that has none yet ─────
    towns = bind.execute(
        sa.text(
            "SELECT t.id, t.name, t.slug FROM towns t "
            "WHERE NOT EXISTS (SELECT 1 FROM localities l WHERE l.town_id = t.id)"
        )
    ).fetchall()
    for town_id, name, slug in towns:
        locality_id = uuid.uuid4().hex
        bind.execute(
            sa.text(
                "INSERT INTO localities (id, town_id, name, slug) "
                "VALUES (:id, :town_id, :name, :slug)"
            ),
            {"id": locality_id, "town_id": town_id, "name": name, "slug": slug},
        )
        bind.execute(
            sa.text(
                "UPDATE town_postal_codes SET locality_id = :lid "
                "WHERE town_id = :town_id AND locality_id IS NULL"
            ),
            {"lid": locality_id, "town_id": town_id},
        )
        bind.execute(
            sa.text(
                "UPDATE shops SET locality_id = :lid "
                "WHERE town_id = :town_id AND locality_id IS NULL"
            ),
            {"lid": locality_id, "town_id": town_id},
        )


def downgrade() -> None:
    op.drop_constraint("fk_shops_locality", "shops", type_="foreignkey")
    op.drop_index("ix_shops_locality_id", table_name="shops")
    op.drop_column("shops", "locality_id")
    op.drop_constraint(
        "fk_town_postal_codes_locality", "town_postal_codes", type_="foreignkey"
    )
    op.drop_index(
        "ix_town_postal_codes_locality_id", table_name="town_postal_codes"
    )
    op.drop_column("town_postal_codes", "locality_id")
    op.drop_index("ix_locality_media_locality_id", table_name="locality_media")
    op.drop_table("locality_media")
    op.drop_index("ix_localities_slug", table_name="localities")
    op.drop_index("ix_localities_town_id", table_name="localities")
    op.drop_table("localities")
