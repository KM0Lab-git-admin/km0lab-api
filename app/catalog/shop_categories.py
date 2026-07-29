"""Canonical shop category catalog (slugs). Labels live in front i18n."""

# (slug, sort_order) — keep in sync with migrations/0011 and i18n shopCategories.*
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
