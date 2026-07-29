"""URL-safe slug helpers."""

from __future__ import annotations

import re
import unicodedata


def slugify(value: str, *, max_len: int = 80) -> str:
    text = unicodedata.normalize("NFKD", value or "")
    text = text.encode("ascii", "ignore").decode("ascii")
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    if not text:
        text = "item"
    return text[:max_len]


def split_full_name(full: str | None) -> tuple[str | None, str | None]:
    """Split 'Nombre Apellido1 Apellido2' → (Nombre, Apellido1 Apellido2)."""
    if not full or not full.strip():
        return None, None
    parts = full.strip().split()
    if len(parts) == 1:
        return parts[0], None
    return parts[0], " ".join(parts[1:])
