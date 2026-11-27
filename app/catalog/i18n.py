"""Shared i18n helpers for JSON multilingual fields (ca/es/en).

Each translatable column stores ``{"ca": "...", "es": "...", "en": "..."}``.
Plain text columns remain as a mirror of the default language for search
and legacy fallbacks. Resolution for public APIs happens server-side via
``resolve_i18n`` (option A: ``?lang=``).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

SUPPORTED_LANGS: tuple[str, ...] = ("ca", "es", "en")
DEFAULT_LANG: str = "ca"

TranslateFn = Callable[[list[str], str, list[str]], Awaitable[dict[str, list[str]]]]


def normalize_lang(value: str | None) -> str:
    lang = (value or "").strip().lower()
    return lang if lang in SUPPORTED_LANGS else DEFAULT_LANG


def resolve_i18n(
    i18n: dict[str, Any] | None,
    lang: str,
    fallback_lang: str = DEFAULT_LANG,
    legacy: str | None = None,
) -> str | None:
    """Pick a localized string from an i18n dict with safe fallbacks."""
    if not i18n:
        return legacy
    val = i18n.get(lang)
    if val:
        return val
    val = i18n.get(fallback_lang)
    if val:
        return val
    val = i18n.get(DEFAULT_LANG)
    if val:
        return val
    # Any remaining non-empty value, then legacy.
    for key in SUPPORTED_LANGS:
        val = i18n.get(key)
        if val:
            return val
    return legacy


def pick_source_lang(
    i18n: dict[str, Any] | None,
    declared: str | None = None,
    fallback: str = DEFAULT_LANG,
) -> str:
    """Choose the source language for auto-translation.

    Preference: declared (if present in i18n with a value) → first filled
    supported lang → fallback.
    """
    declared_norm = normalize_lang(declared) if declared else None
    if declared_norm and i18n and (i18n.get(declared_norm) or "").strip():
        return declared_norm
    if i18n:
        for lang in SUPPORTED_LANGS:
            if (i18n.get(lang) or "").strip():
                return lang
    return declared_norm or normalize_lang(fallback)


def ensure_i18n_dict(
    i18n: dict[str, Any] | None,
    *,
    legacy: str | None = None,
    source_lang: str = DEFAULT_LANG,
) -> dict[str, str]:
    """Normalize a partial i18n payload into a ca/es/en dict (may have holes)."""
    out: dict[str, str] = {lang: "" for lang in SUPPORTED_LANGS}
    if i18n:
        for lang in SUPPORTED_LANGS:
            val = i18n.get(lang)
            if isinstance(val, str) and val.strip():
                out[lang] = val.strip()
    src = normalize_lang(source_lang)
    if not out[src] and legacy and legacy.strip():
        out[src] = legacy.strip()
    return out


async def merge_and_translate(
    i18n: dict[str, Any] | None,
    *,
    source_lang: str | None = None,
    legacy: str | None = None,
    translate_fn: TranslateFn | None = None,
) -> dict[str, str]:
    """Fill missing languages in an i18n dict via ``translate_fn``.

    Returns a complete ``{ca, es, en}`` dict. Empty targets are filled by
    translating from the source language. If ``translate_fn`` is None or
    fails internally, callers should pass a degrading translator that
    copies the source text.
    """
    src = pick_source_lang(i18n, source_lang)
    filled = ensure_i18n_dict(i18n, legacy=legacy, source_lang=src)
    source_text = filled.get(src) or ""
    missing = [lang for lang in SUPPORTED_LANGS if lang != src and not filled[lang]]

    if not missing or not source_text:
        # Still ensure every key exists (copy source into holes if no translator).
        if source_text:
            for lang in missing:
                filled[lang] = source_text
        return filled

    if translate_fn is None:
        for lang in missing:
            filled[lang] = source_text
        return filled

    translated = await translate_fn([source_text], src, missing)
    for lang in missing:
        vals = translated.get(lang) or []
        filled[lang] = (vals[0] if vals else source_text) or source_text
    return filled


def mirror_plain(i18n: dict[str, str] | None, lang: str = DEFAULT_LANG) -> str:
    """Plain-column mirror of the given language (default ca)."""
    if not i18n:
        return ""
    return (i18n.get(lang) or i18n.get(DEFAULT_LANG) or next(iter(i18n.values()), "")) or ""
