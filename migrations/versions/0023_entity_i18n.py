"""i18n JSON columns for rewards, promotions, shops, shop_categories + point_actions conditions.

Revision ID: 0023_entity_i18n
Revises: 0022_action_i18n
Create Date: 2026-07-29
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0023_entity_i18n"
down_revision: Union[str, None] = "0022_action_i18n"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Seed labels for known shop category slugs (ca/es/en).
_CATEGORY_LABELS = {
    "bakery": {"ca": "Fleca", "es": "Panadería", "en": "Bakery"},
    "food": {"ca": "Alimentació", "es": "Alimentación", "en": "Food"},
    "cafe": {"ca": "Cafeteria", "es": "Cafetería", "en": "Café"},
    "restaurant": {"ca": "Restauració", "es": "Restauración", "en": "Restaurant"},
    "bar": {"ca": "Bar", "es": "Bar", "en": "Bar"},
    "butcher": {"ca": "Carnisseria", "es": "Carnicería", "en": "Butcher"},
    "greengrocer": {"ca": "Fruiteria", "es": "Frutería", "en": "Greengrocer"},
    "fishmonger": {"ca": "Peixateria", "es": "Pescadería", "en": "Fishmonger"},
    "pharmacy": {"ca": "Farmàcia", "es": "Farmacia", "en": "Pharmacy"},
    "bookstore": {"ca": "Llibreria", "es": "Librería", "en": "Bookstore"},
    "clothing": {"ca": "Moda", "es": "Moda", "en": "Clothing"},
    "hairdresser": {"ca": "Perruqueria", "es": "Peluquería", "en": "Hairdresser"},
    "services": {"ca": "Serveis", "es": "Servicios", "en": "Services"},
    "other": {"ca": "Altres", "es": "Otros", "en": "Other"},
}


def upgrade() -> None:
    # ── point_actions: conditions_i18n + i18n_source_lang ──────────────
    op.add_column("point_actions", sa.Column("conditions_i18n", sa.JSON(), nullable=True))
    op.add_column(
        "point_actions",
        sa.Column("i18n_source_lang", sa.String(length=5), nullable=False, server_default="ca"),
    )
    op.execute(
        "UPDATE point_actions SET conditions_i18n = JSON_OBJECT('ca', conditions) "
        "WHERE conditions IS NOT NULL AND conditions_i18n IS NULL"
    )

    # ── rewards ───────────────────────────────────────────────────────
    op.add_column("rewards", sa.Column("name_i18n", sa.JSON(), nullable=True))
    op.add_column("rewards", sa.Column("description_i18n", sa.JSON(), nullable=True))
    op.add_column("rewards", sa.Column("conditions_i18n", sa.JSON(), nullable=True))
    op.add_column(
        "rewards",
        sa.Column("i18n_source_lang", sa.String(length=5), nullable=False, server_default="ca"),
    )
    # Backfill using the town's default_lang when available, else 'ca'.
    op.execute(
        """
        UPDATE rewards r
        LEFT JOIN towns t ON t.id = r.town_id
        SET r.name_i18n = JSON_OBJECT(COALESCE(NULLIF(t.default_lang, ''), 'ca'), r.name)
        WHERE r.name_i18n IS NULL
        """
    )
    op.execute(
        """
        UPDATE rewards r
        LEFT JOIN towns t ON t.id = r.town_id
        SET r.description_i18n = JSON_OBJECT(COALESCE(NULLIF(t.default_lang, ''), 'ca'), r.description)
        WHERE r.description_i18n IS NULL
        """
    )
    op.execute(
        """
        UPDATE rewards r
        LEFT JOIN towns t ON t.id = r.town_id
        SET r.conditions_i18n = JSON_OBJECT(COALESCE(NULLIF(t.default_lang, ''), 'ca'), r.conditions)
        WHERE r.conditions IS NOT NULL AND r.conditions_i18n IS NULL
        """
    )
    op.execute(
        """
        UPDATE rewards r
        LEFT JOIN towns t ON t.id = r.town_id
        SET r.i18n_source_lang = COALESCE(NULLIF(t.default_lang, ''), 'ca')
        """
    )

    # ── promotions (via shop → town) ──────────────────────────────────
    op.add_column("promotions", sa.Column("label_i18n", sa.JSON(), nullable=True))
    op.add_column("promotions", sa.Column("title_i18n", sa.JSON(), nullable=True))
    op.add_column("promotions", sa.Column("detail_i18n", sa.JSON(), nullable=True))
    op.add_column("promotions", sa.Column("conditions_i18n", sa.JSON(), nullable=True))
    op.add_column(
        "promotions",
        sa.Column("i18n_source_lang", sa.String(length=5), nullable=False, server_default="ca"),
    )
    op.execute(
        """
        UPDATE promotions p
        LEFT JOIN shops s ON s.id = p.shop_id
        LEFT JOIN towns t ON t.id = s.town_id
        SET p.label_i18n = JSON_OBJECT(COALESCE(NULLIF(t.default_lang, ''), 'ca'), p.label)
        WHERE p.label_i18n IS NULL
        """
    )
    op.execute(
        """
        UPDATE promotions p
        LEFT JOIN shops s ON s.id = p.shop_id
        LEFT JOIN towns t ON t.id = s.town_id
        SET p.title_i18n = JSON_OBJECT(COALESCE(NULLIF(t.default_lang, ''), 'ca'), p.title)
        WHERE p.title_i18n IS NULL
        """
    )
    op.execute(
        """
        UPDATE promotions p
        LEFT JOIN shops s ON s.id = p.shop_id
        LEFT JOIN towns t ON t.id = s.town_id
        SET p.detail_i18n = JSON_OBJECT(COALESCE(NULLIF(t.default_lang, ''), 'ca'), p.detail)
        WHERE p.detail_i18n IS NULL
        """
    )
    op.execute(
        """
        UPDATE promotions p
        LEFT JOIN shops s ON s.id = p.shop_id
        LEFT JOIN towns t ON t.id = s.town_id
        SET p.conditions_i18n = JSON_OBJECT(COALESCE(NULLIF(t.default_lang, ''), 'ca'), p.conditions)
        WHERE p.conditions IS NOT NULL AND p.conditions_i18n IS NULL
        """
    )
    op.execute(
        """
        UPDATE promotions p
        LEFT JOIN shops s ON s.id = p.shop_id
        LEFT JOIN towns t ON t.id = s.town_id
        SET p.i18n_source_lang = COALESCE(NULLIF(t.default_lang, ''), 'ca')
        """
    )

    # ── shops ─────────────────────────────────────────────────────────
    op.add_column("shops", sa.Column("description_i18n", sa.JSON(), nullable=True))
    op.add_column(
        "shops",
        sa.Column("i18n_source_lang", sa.String(length=5), nullable=False, server_default="ca"),
    )
    op.execute(
        """
        UPDATE shops s
        LEFT JOIN towns t ON t.id = s.town_id
        SET s.description_i18n = JSON_OBJECT(COALESCE(NULLIF(t.default_lang, ''), 'ca'), s.description)
        WHERE s.description IS NOT NULL AND s.description_i18n IS NULL
        """
    )
    op.execute(
        """
        UPDATE shops s
        LEFT JOIN towns t ON t.id = s.town_id
        SET s.i18n_source_lang = COALESCE(NULLIF(t.default_lang, ''), 'ca')
        """
    )

    # ── shop_categories ───────────────────────────────────────────────
    op.add_column("shop_categories", sa.Column("label_i18n", sa.JSON(), nullable=True))
    op.add_column(
        "shop_categories",
        sa.Column("i18n_source_lang", sa.String(length=5), nullable=False, server_default="ca"),
    )
    # Seed known category labels.
    import json

    conn = op.get_bind()
    for slug, labels in _CATEGORY_LABELS.items():
        conn.execute(
            sa.text(
                "UPDATE shop_categories SET label_i18n = :labels, i18n_source_lang = 'ca' "
                "WHERE slug = :slug"
            ),
            {"labels": json.dumps(labels, ensure_ascii=False), "slug": slug},
        )


def downgrade() -> None:
    op.drop_column("shop_categories", "i18n_source_lang")
    op.drop_column("shop_categories", "label_i18n")

    op.drop_column("shops", "i18n_source_lang")
    op.drop_column("shops", "description_i18n")

    op.drop_column("promotions", "i18n_source_lang")
    op.drop_column("promotions", "conditions_i18n")
    op.drop_column("promotions", "detail_i18n")
    op.drop_column("promotions", "title_i18n")
    op.drop_column("promotions", "label_i18n")

    op.drop_column("rewards", "i18n_source_lang")
    op.drop_column("rewards", "conditions_i18n")
    op.drop_column("rewards", "description_i18n")
    op.drop_column("rewards", "name_i18n")

    op.drop_column("point_actions", "i18n_source_lang")
    op.drop_column("point_actions", "conditions_i18n")
