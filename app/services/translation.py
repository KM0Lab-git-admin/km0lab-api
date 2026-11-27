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
        result = await _call_openai(
            api_key, settings.openai_translate_model, texts, src, clean_targets
        )
        # Retry targets that came back empty or identical to source (common
        # failure for Spanish→Catalan when the model omits the ``ca`` key).
        retry_targets = [
            lang
            for lang in clean_targets
            if _needs_retry(texts, result.get(lang) or [])
        ]
        if retry_targets:
            logger.info(
                "Retrying translation for targets=%s source=%s",
                retry_targets,
                src,
            )
            retry = await _call_openai(
                api_key,
                settings.openai_translate_model,
                texts,
                src,
                retry_targets,
                strict=True,
            )
            for lang in retry_targets:
                result[lang] = retry.get(lang) or result.get(lang) or []

        out: dict[str, list[str]] = {}
        for lang in clean_targets:
            vals = result.get(lang) or []
            filled: list[str] = []
            for i, original in enumerate(texts):
                candidate = vals[i] if i < len(vals) else None
                if isinstance(candidate, str) and candidate.strip():
                    filled.append(candidate.strip())
                else:
                    filled.append(original)
            out[lang] = filled
        return out
    except Exception:
        logger.exception("OpenAI translation failed — copying source text")
        return {t: list(texts) for t in clean_targets}


def _needs_retry(texts: list[str], vals: list[str]) -> bool:
    if len(vals) < len(texts):
        return True
    for i, original in enumerate(texts):
        candidate = vals[i] if i < len(vals) else ""
        if not isinstance(candidate, str) or not candidate.strip():
            return True
        # Identical copy is almost always wrong for distinct language pairs.
        if candidate.strip() == original.strip():
            return True
    return False


async def _call_openai(
    api_key: str,
    model: str,
    texts: list[str],
    source: str,
    targets: list[str],
    *,
    strict: bool = False,
) -> dict[str, list[str]]:
    example_keys = ", ".join(f'"{t}": ["..."]' for t in targets)
    must_differ = (
        " Each translation MUST be written in the target language and MUST "
        "differ from the source text when source and target are different "
        "languages (especially Spanish vs Catalan)."
        if strict
        else ""
    )
    system = (
        "You are a professional translator for a municipal loyalty app. "
        "Translate faithfully, keep tone and proper names. "
        "Return ONLY valid JSON whose keys are EXACTLY the target language "
        f"codes ({', '.join(targets)}), of the form {{{example_keys}}} "
        "with one string per input text, same order, no extra keys."
        f"{must_differ}"
    )
    payload: dict[str, Any] = {
        "model": model,
        "temperature": 0.2 if not strict else 0.3,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": system},
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "source_lang": _LANG_NAMES.get(source, source),
                        "source_code": source,
                        "target_langs": [_LANG_NAMES.get(t, t) for t in targets],
                        "target_codes": targets,
                        "texts": texts,
                        "instruction": (
                            f"Translate each text from {source} into every "
                            f"target_codes language. Keys in the JSON response "
                            f"must be exactly: {targets}."
                        ),
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
    if not isinstance(parsed, dict):
        return {code: [] for code in targets}

    # Accept target codes, full language names, or nested {translations: {...}}.
    nested = parsed.get("translations")
    if isinstance(nested, dict):
        parsed = {**parsed, **nested}

    out: dict[str, list[str]] = {}
    for code in targets:
        raw = parsed.get(code)
        if raw is None:
            raw = parsed.get(_LANG_NAMES.get(code, code))
        if raw is None:
            # Model sometimes returns uppercase codes.
            raw = parsed.get(code.upper())
        if isinstance(raw, list):
            out[code] = [str(x) if x is not None else "" for x in raw]
        elif isinstance(raw, str):
            out[code] = [raw]
        else:
            out[code] = []
    return out
