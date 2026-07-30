"""Add emoji to shop_categories.

Revision ID: 0024_shop_category_emoji
Revises: 0023_entity_i18n
Create Date: 2026-07-30
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0024_shop_category_emoji"
down_revision: Union[str, None] = "0023_entity_i18n"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Keep in sync with app/catalog/shop_categories.DEFAULT_SHOP_CATEGORY_EMOJIS
_CATEGORY_EMOJIS = {
    "bakery": "🥖",
    "food": "🛒",
    "cafe": "☕",
    "restaurant": "🍽️",
    "bar": "🍺",
    "butcher": "🥩",
    "greengrocer": "🍎",
    "fishmonger": "🐟",
    "pharmacy": "💊",
    "bookstore": "📚",
    "clothing": "👗",
    "hairdresser": "✂️",
    "services": "💻",
    "other": "📦",
}


def upgrade() -> None:
    op.add_column(
        "shop_categories",
        sa.Column("emoji", sa.String(length=16), nullable=True),
    )
    conn = op.get_bind()
    for slug, emoji in _CATEGORY_EMOJIS.items():
        conn.execute(
            sa.text("UPDATE shop_categories SET emoji = :emoji WHERE slug = :slug"),
            {"emoji": emoji, "slug": slug},
        )


def downgrade() -> None:
    op.drop_column("shop_categories", "emoji")
