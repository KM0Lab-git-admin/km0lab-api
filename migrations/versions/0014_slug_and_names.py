"""Add slug to towns/users; split users.name into first_name + last_name

Revision ID: 0014_slug_and_names
Revises: 0013_shop_media_longblob
Create Date: 2026-07-28
"""

from __future__ import annotations

import re
import unicodedata
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0014_slug_and_names"
down_revision: Union[str, None] = "0013_shop_media_longblob"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _slugify(value: str, *, max_len: int = 80) -> str:
    text = unicodedata.normalize("NFKD", value or "")
    text = text.encode("ascii", "ignore").decode("ascii")
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    if not text:
        text = "item"
    return text[:max_len]


def _unique(base: str, used: set[str]) -> str:
    slug = base
    n = 2
    while slug in used:
        suffix = f"-{n}"
        slug = f"{base[: 80 - len(suffix)]}{suffix}"
        n += 1
    used.add(slug)
    return slug


def upgrade() -> None:
    op.add_column("towns", sa.Column("slug", sa.String(length=80), nullable=True))
    op.add_column("users", sa.Column("slug", sa.String(length=80), nullable=True))
    op.add_column(
        "users", sa.Column("first_name", sa.String(length=80), nullable=True)
    )
    op.add_column(
        "users", sa.Column("last_name", sa.String(length=120), nullable=True)
    )

    conn = op.get_bind()

    used_town: set[str] = set()
    for town_id, name in conn.execute(sa.text("SELECT id, name FROM towns")):
        slug = _unique(_slugify(name or town_id), used_town)
        conn.execute(
            sa.text("UPDATE towns SET slug = :s WHERE id = :id"),
            {"s": slug, "id": town_id},
        )

    used_user: set[str] = set()
    for user_id, email, name in conn.execute(
        sa.text("SELECT id, email, name FROM users")
    ):
        full = (name or "").strip()
        if full:
            parts = full.split()
            first = parts[0]
            last = " ".join(parts[1:]) if len(parts) > 1 else None
        else:
            first, last = None, None
        base = _slugify(
            f"{first or ''} {last or ''}".strip()
            or (email or "").split("@")[0]
            or user_id
        )
        slug = _unique(base, used_user)
        conn.execute(
            sa.text(
                "UPDATE users SET slug = :s, first_name = :f, last_name = :l "
                "WHERE id = :id"
            ),
            {"s": slug, "f": first, "l": last, "id": user_id},
        )

    op.alter_column(
        "towns",
        "slug",
        existing_type=sa.String(length=80),
        nullable=False,
    )
    op.alter_column(
        "users",
        "slug",
        existing_type=sa.String(length=80),
        nullable=False,
    )
    op.create_index("ix_towns_slug", "towns", ["slug"], unique=True)
    op.create_index("ix_users_slug", "users", ["slug"], unique=True)
    op.drop_column("users", "name")


def downgrade() -> None:
    op.add_column(
        "users", sa.Column("name", sa.String(length=120), nullable=True)
    )
    conn = op.get_bind()
    for user_id, first, last in conn.execute(
        sa.text("SELECT id, first_name, last_name FROM users")
    ):
        parts = [p for p in (first, last) if p]
        name = " ".join(parts) or None
        conn.execute(
            sa.text("UPDATE users SET name = :n WHERE id = :id"),
            {"n": name, "id": user_id},
        )
    op.drop_index("ix_users_slug", table_name="users")
    op.drop_index("ix_towns_slug", table_name="towns")
    op.drop_column("users", "last_name")
    op.drop_column("users", "first_name")
    op.drop_column("users", "slug")
    op.drop_column("towns", "slug")
