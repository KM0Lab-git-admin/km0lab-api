"""Canonical shop category catalog (slugs + default emojis).

Labels live in DB `label_i18n` (with legacy front i18n as fallback).
"""

# (slug, sort_order) — keep in sync with migrations/0011
DEFAULT_SHOP_CATEGORIES: tuple[tuple[str, int], ...] = (
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

# Representative emoji per slug — keep in sync with migration backfill.
DEFAULT_SHOP_CATEGORY_EMOJIS: dict[str, str] = {
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
