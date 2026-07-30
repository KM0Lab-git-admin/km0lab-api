"""OpenAI-backed translation helper with graceful degradation.

If ``OPENAI_API_KEY`` is missing or the call fails, each target language
receives a copy of the source text so saves never block on translation.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx

from app.catalog.i18n import normalize_lang
from app.config import get_settings

logger = logging.getLogger(__name__)

_LANG_NAMES = {"ca": "Catalan", "es": "Spanish", "en": "English"}


async def translate_texts(
    texts: list[str],
    source: str,
    targets: list[str],
) -> dict[str, list[str]]:
    """Translate ``texts`` from ``source`` into each of ``targets``.

    Returns ``{lang: [translated_or_copied, ...]}`` aligned with ``texts``.
    Never raises: on any failure, copies the source text into each target.
    """
    src = normalize_lang(source)
    clean_targets = [
        lang
        for lang in (normalize_lang(t) for t in targets)
        if lang != src
    ]
    # de-dupe while preserving order
    seen: set[str] = set()
    clean_targets = [t for t in clean_targets if not (t in seen or seen.add(t))]
    if not texts or not clean_targets:
        return {t: list(texts) for t in clean_targets}

    settings = get_settings()
    api_key = (settings.openai_api_key or "").strip()
    if not api_key:
        logger.info("OPENAI_API_KEY missing — copying source text for translation")
        return {t: list(texts) for t in clean_targets}

    try:
        result = await _call_openai(api_key, settings.openai_translate_model, texts, src, clean_targets)
        # Ensure every target/index is filled.
        out: dict[str, list[str]] = {}
        for lang in clean_targets:
            vals = result.get(lang) or []
            filled: list[str] = []
            for i, original in enumerate(texts):
                candidate = vals[i] if i < len(vals) else None
                filled.append(candidate.strip() if isinstance(candidate, str) and candidate.strip() else original)
            out[lang] = filled
        return out
    except Exception:
        logger.exception("OpenAI translation failed — copying source text")
        return {t: list(texts) for t in clean_targets}


async def _call_openai(
    api_key: str,
    model: str,
    texts: list[str],
    source: str,
    targets: list[str],
) -> dict[str, list[str]]:
    system = (
        "You are a professional translator for a municipal loyalty app. "
        "Translate faithfully, keep tone and proper names. "
        "Return ONLY valid JSON of the form "
        '{"es": ["..."], "en": ["..."]} with one string per input text, '
        "same order, no extra keys."
    )
    payload: dict[str, Any] = {
        "model": model,
        "temperature": 0.2,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": system},
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "source_lang": _LANG_NAMES.get(source, source),
                        "target_langs": [_LANG_NAMES.get(t, t) for t in targets],
                        "target_codes": targets,
                        "texts": texts,
                    },
                    ensure_ascii=False,
                ),
            },
        ],
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            "https://api.openai.com/v1/chat/completions",
            headers=headers,
            json=payload,
        )
        resp.raise_for_status()
        body = resp.json()

    content = body["choices"][0]["message"]["content"]
    parsed = json.loads(content)
    # Accept either target codes or full language names as keys.
    out: dict[str, list[str]] = {}
    for code in targets:
        raw = parsed.get(code)
        if raw is None:
            name = _LANG_NAMES.get(code, code)
            raw = parsed.get(name)
        if isinstance(raw, list):
            out[code] = [str(x) if x is not None else "" for x in raw]
        elif isinstance(raw, str):
            out[code] = [raw]
        else:
            out[code] = []
    return out
