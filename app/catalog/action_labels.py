"""Fixed point-action catalog labels (ca/es/en).

For fixed action types (signup, birthday, qr_scan, first_scan, web_visit,
web_signup, event) the resident-facing name/description are NOT editable in
the BO and are served translated from this catalog by the requested lang.
Only ``custom`` actions store admin-written text (name_i18n / description_i18n).
"""

from __future__ import annotations

# Re-export shared i18n constants/helpers for backward-compatible imports.
from app.catalog.i18n import (  # noqa: F401
    DEFAULT_LANG,
    SUPPORTED_LANGS,
    normalize_lang,
    resolve_i18n,
)

# type -> lang -> {name, description}
FIXED_ACTION_LABELS: dict[str, dict[str, dict[str, str]]] = {
    "signup": {
        "ca": {"name": "Primer registre a l'app", "description": "Punts de benvinguda"},
        "es": {"name": "Primer registro en la app", "description": "Puntos de bienvenida"},
        "en": {"name": "First app registration", "description": "Welcome points"},
    },
    "birthday": {
        "ca": {"name": "Perquè avui és el teu aniversari!", "description": "Punts pel teu aniversari"},
        "es": {"name": "¡Porque hoy es tu cumpleaños!", "description": "Puntos por tu cumpleaños"},
        "en": {"name": "Because it's your birthday!", "description": "Birthday points"},
    },
    "qr_scan": {
        "ca": {"name": "Escaneig d'un comerç", "description": "Visita a un comerç adherit"},
        "es": {"name": "Escaneo de un comercio", "description": "Visita a un comercio adherido"},
        "en": {"name": "Merchant scan", "description": "Visit to a partner shop"},
    },
    "first_scan": {
        "ca": {"name": "Primer escaneig d'un comerç", "description": "Bonificació única la primera vegada que s'escaneja un QR de comerç"},
        "es": {"name": "Primer escaneo de un comercio", "description": "Bonificación única la primera vez que se escanea un QR de comercio"},
        "en": {"name": "First merchant scan", "description": "One-time bonus the first time a merchant QR is scanned"},
    },
    "web_visit": {
        "ca": {"name": "Visita la web de turisme", "description": "Visita la web municipal de turisme"},
        "es": {"name": "Visita la web de turismo", "description": "Visita la web municipal de turismo"},
        "en": {"name": "Visit the tourism website", "description": "Visit the municipal tourism website"},
    },
    "web_signup": {
        "ca": {"name": "Registre al butlletí municipal", "description": "Subscripció al butlletí"},
        "es": {"name": "Registro al boletín municipal", "description": "Suscripción al boletín"},
        "en": {"name": "Newsletter signup", "description": "Subscribe to the newsletter"},
    },
    "event": {
        "ca": {"name": "Inscripció a la Festa Major", "description": "Inscripció a un esdeveniment municipal"},
        "es": {"name": "Inscripción a la Fiesta Mayor", "description": "Inscripción a un evento municipal"},
        "en": {"name": "Festa Major signup", "description": "Signup to a municipal event"},
    },
}

FIXED_ACTION_TYPES: frozenset[str] = frozenset(FIXED_ACTION_LABELS.keys())


def is_fixed_action_type(type_: str) -> bool:
    return type_ in FIXED_ACTION_TYPES


def fixed_label(type_: str, lang: str) -> dict[str, str]:
    """Resolved {name, description} for a fixed type in the requested lang."""
    catalog = FIXED_ACTION_LABELS.get(type_, {})
    return catalog.get(lang) or catalog.get(DEFAULT_LANG) or {"name": "", "description": ""}


def fixed_i18n(type_: str) -> dict[str, dict[str, str]]:
    """Full i18n payload {ca/es/en: {name, description}} for a fixed type."""
    return {
        lang: FIXED_ACTION_LABELS[type_].get(lang, FIXED_ACTION_LABELS[type_][DEFAULT_LANG])
        for lang in SUPPORTED_LANGS
    }
