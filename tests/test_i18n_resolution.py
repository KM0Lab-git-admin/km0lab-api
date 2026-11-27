"""Unit tests for shared i18n helpers (resolve / merge / translate)."""

from __future__ import annotations

import pytest

from app.catalog.i18n import (
    DEFAULT_LANG,
    ensure_i18n_dict,
    merge_and_translate,
    normalize_lang,
    pick_source_lang,
    resolve_i18n,
)


def test_normalize_lang():
    assert normalize_lang("ES") == "es"
    assert normalize_lang("en") == "en"
    assert normalize_lang("xx") == DEFAULT_LANG
    assert normalize_lang(None) == DEFAULT_LANG


def test_resolve_i18n_prefers_requested_lang():
    i18n = {"ca": "Hola", "es": "Hola ES", "en": "Hello"}
    assert resolve_i18n(i18n, "es") == "Hola ES"
    assert resolve_i18n(i18n, "en") == "Hello"
    assert resolve_i18n(i18n, "ca") == "Hola"


def test_resolve_i18n_fallbacks():
    i18n = {"ca": "Hola"}
    assert resolve_i18n(i18n, "es", fallback_lang="ca") == "Hola"
    assert resolve_i18n(None, "es", legacy="legacy") == "legacy"
    assert resolve_i18n({}, "es", legacy="legacy") == "legacy"


def test_pick_source_lang():
    assert pick_source_lang({"es": "Hola"}, declared="es") == "es"
    assert pick_source_lang({"ca": "Hola"}, declared="en") == "ca"
    assert pick_source_lang({}, declared="en") == "en"
    assert pick_source_lang(None) == DEFAULT_LANG


def test_ensure_i18n_dict_seeds_legacy():
    out = ensure_i18n_dict(None, legacy="Texto", source_lang="ca")
    assert out["ca"] == "Texto"
    assert out["es"] == ""
    assert out["en"] == ""


@pytest.mark.asyncio
async def test_merge_and_translate_copies_without_fn():
    filled = await merge_and_translate(
        {"ca": "Hola"},
        source_lang="ca",
        translate_fn=None,
    )
    assert filled == {"ca": "Hola", "es": "Hola", "en": "Hola"}


@pytest.mark.asyncio
async def test_merge_and_translate_with_mock_fn():
    async def fake_translate(texts, source, targets):
        assert source == "ca"
        assert texts == ["Hola"]
        return {t: [f"{t}:{texts[0]}"] for t in targets}

    filled = await merge_and_translate(
        {"ca": "Hola"},
        source_lang="ca",
        translate_fn=fake_translate,
    )
    assert filled["ca"] == "Hola"
    assert filled["es"] == "es:Hola"
    assert filled["en"] == "en:Hola"


@pytest.mark.asyncio
async def test_merge_keeps_existing_translations():
    async def fill_en(texts, source, targets):
        assert targets == ["en"]
        return {t: [f"EN:{texts[0]}"] for t in targets}

    filled = await merge_and_translate(
        {"ca": "Hola", "es": "Hola ES"},
        source_lang="ca",
        translate_fn=fill_en,
    )
    assert filled["es"] == "Hola ES"
    assert filled["en"] == "EN:Hola"
