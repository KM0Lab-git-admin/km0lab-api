"""Apply / resolve multilingual JSON fields on domain models."""

from __future__ import annotations

from typing import Any

from app.catalog.i18n import (
    DEFAULT_LANG,
    merge_and_translate,
    mirror_plain,
    normalize_lang,
    pick_source_lang,
    resolve_i18n,
)
from app.services.translation import translate_texts


async def fill_i18n_field(
    payload_i18n: dict[str, Any] | None,
    *,
    legacy: str | None,
    source_lang: str | None,
) -> dict[str, str]:
    """Complete an i18n dict (auto-translate missing langs)."""
    return await merge_and_translate(
        payload_i18n,
        source_lang=source_lang,
        legacy=legacy,
        translate_fn=translate_texts,
    )


async def apply_text_i18n(
    *,
    payload_i18n: dict[str, Any] | None,
    payload_plain: str | None,
    existing_i18n: dict[str, Any] | None,
    existing_plain: str | None,
    source_lang: str | None,
    default_lang: str = DEFAULT_LANG,
) -> tuple[dict[str, str], str]:
    """Merge payload into existing i18n, translate holes, return (i18n, plain).

    Prefer payload_i18n when provided; otherwise bootstrap from payload_plain
    or existing values. Plain mirror uses ``default_lang``.
    """
    base: dict[str, Any] = dict(existing_i18n or {})
    if payload_i18n is not None:
        for lang, val in payload_i18n.items():
            if isinstance(val, str) and val.strip():
                base[lang] = val.strip()
            elif val is None or (isinstance(val, str) and not val.strip()):
                # Explicit empty → leave hole for translator.
                base.pop(lang, None)
    elif payload_plain is not None:
        src = pick_source_lang(base, source_lang, fallback=default_lang)
        base[src] = payload_plain.strip()

    filled = await fill_i18n_field(
        base or None,
        legacy=payload_plain if payload_plain is not None else existing_plain,
        source_lang=source_lang or pick_source_lang(base, fallback=default_lang),
    )
    plain = mirror_plain(filled, normalize_lang(default_lang))
    return filled, plain


def resolve_field(
    i18n: dict[str, Any] | None,
    lang: str,
    fallback_lang: str,
    legacy: str | None,
) -> str | None:
    return resolve_i18n(i18n, lang, fallback_lang, legacy=legacy)
