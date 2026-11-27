"""Apply / resolve multilingual JSON fields on domain models."""

from __future__ import annotations

from typing import Any

from app.catalog.i18n import (
    DEFAULT_LANG,
    SUPPORTED_LANGS,
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

    If the source-language text changes and the client re-sends the previous
    translations for other langs unchanged, those langs are treated as holes
    so OpenAI (or copy-fallback) can refill them. Explicitly edited target
    langs (value differs from what was stored) are kept.
    """
    existing: dict[str, Any] = dict(existing_i18n or {})
    src = normalize_lang(
        source_lang or pick_source_lang(existing, fallback=default_lang)
    )
    old_src = (
        (existing.get(src) or "").strip()
        or (existing_plain or "").strip()
    )

    base: dict[str, Any] = dict(existing)
    if payload_i18n is not None:
        for lang, val in payload_i18n.items():
            if isinstance(val, str) and val.strip():
                base[lang] = val.strip()
            elif val is None or (isinstance(val, str) and not val.strip()):
                # Explicit empty → leave hole for translator.
                base.pop(lang, None)
    elif payload_plain is not None:
        base[src] = payload_plain.strip()

    # Re-resolve source after merge (payload may have filled it).
    src = pick_source_lang(base, source_lang, fallback=default_lang)
    new_src = (base.get(src) or "").strip()
    if (
        payload_i18n is not None
        and new_src
        and old_src
        and new_src != old_src
    ):
        for lang in SUPPORTED_LANGS:
            if lang == src:
                continue
            payload_val = payload_i18n.get(lang)
            old_val = (existing.get(lang) or "").strip()
            if isinstance(payload_val, str) and payload_val.strip():
                if payload_val.strip() == old_val:
                    # Stale translation echoed by the client — retranslate.
                    base.pop(lang, None)
                # else: client sent a new explicit translation → keep
            elif payload_val is None:
                # Key omitted while source changed → do not keep stale.
                base.pop(lang, None)
            else:
                base.pop(lang, None)

    filled = await fill_i18n_field(
        base or None,
        legacy=payload_plain if payload_plain is not None else existing_plain,
        source_lang=source_lang or src,
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
