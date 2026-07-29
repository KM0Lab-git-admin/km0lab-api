"""Shop categories catalog (slugs; labels in front i18n)

Revision ID: 0011_shop_categories
Revises: 0010_is_fake
Create Date: 2026-07-28
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0011_shop_categories"
down_revision: Union[str, None] = "0010_is_fake"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# slug -> sort_order. Labels live in app/backoffice i18n (shopCategories.{slug}).
# Keep in sync with app/catalog/shop_categories.py
_SEED = (
    ("bakery", 10),
    ("food", 20),
    ("cafe", 30),
    ("restaurant", 40),
    ("bar", 50),
    ("butcher", 60),
    ("greengrocer", 70),
    ("fishmonger", 80),
    ("pharmacy", 90),
    ("bookstore", 100),
    ("clothing", 110),
    ("hairdresser", 120),
    ("services", 130),
    ("other", 999),
)

_LEGACY_LABEL_TO_SLUG = {
    "fleca": "bakery",
    "alimentació": "food",
    "alimentacion": "food",
    "cafe": "cafe",
    "cafeteria": "cafe",
    "cafetería": "cafe",
}


def upgrade() -> None:
    op.create_table(
        "shop_categories",
        sa.Column("slug", sa.String(length=40), primary_key=True),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
    )
    op.create_index("ix_shop_categories_active", "shop_categories", ["active"])

    categories = sa.table(
        "shop_categories",
        sa.column("slug", sa.String),
        sa.column("sort_order", sa.Integer),
        sa.column("active", sa.Boolean),
    )
    op.bulk_insert(
        categories,
        [
            {"slug": slug, "sort_order": order, "active": True}
            for slug, order in _SEED
        ],
    )

    conn = op.get_bind()
    valid = {slug for slug, _ in _SEED}
    rows = conn.execute(sa.text("SELECT id, categories FROM shops")).fetchall()
    import json

    for shop_id, cats in rows:
        if not cats:
            continue
        if isinstance(cats, str):
            cats = json.loads(cats)
        mapped: list[str] = []
        seen: set[str] = set()
        for raw in cats:
            key = str(raw).strip()
            slug = _LEGACY_LABEL_TO_SLUG.get(key.lower())
            if slug is None:
                candidate = key.lower().replace(" ", "-")
                slug = candidate if candidate in valid else None
            if slug and slug in valid and slug not in seen:
                seen.add(slug)
                mapped.append(slug)
        conn.execute(
            sa.text("UPDATE shops SET categories = :c WHERE id = :id"),
            {"c": json.dumps(mapped, ensure_ascii=False), "id": shop_id},
        )


def downgrade() -> None:
    op.drop_index("ix_shop_categories_active", table_name="shop_categories")
    op.drop_table("shop_categories")
