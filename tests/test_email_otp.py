"""The access-code email: subject, text and HTML."""

import re

import pytest

from app.catalog.email_otp import (
    OTP_COPY,
    OTP_DEFAULT_LANG,
    normalize_otp_lang,
    otp_subject,
    render_otp_html,
    render_otp_text,
)

LANGS = ("ca", "es", "en")
CODE = "482913"


def _filled(key: str, lang: str, *, minutes: int = 10) -> str:
    """A text with the code and the minutes in, as the email carries it."""
    return (
        OTP_COPY[key][lang].replace("{code}", CODE).replace("{minutes}", str(minutes))
    )


def _in_html(text: str) -> str:
    """How a text sits in the HTML: escaped, with the brand kept in one line."""
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace("KM0 LAB", "KM0&nbsp;LAB")
    )


def test_normalize_otp_lang_defaults_to_spanish():
    assert OTP_DEFAULT_LANG == "es"
    assert normalize_otp_lang(None) == "es"
    assert normalize_otp_lang("") == "es"
    assert normalize_otp_lang("fr") == "es"
    assert normalize_otp_lang("CA") == "ca"
    assert normalize_otp_lang("es") == "es"
    assert normalize_otp_lang("en") == "en"


def test_every_text_exists_in_the_three_languages():
    assert set(OTP_COPY) == {
        "subject",
        "preheader",
        "title",
        "intro",
        "validity",
        "not_you",
        "footer_signature",
    }
    for key, row in OTP_COPY.items():
        assert set(row) == set(LANGS), key
        assert all(row[lang].strip() for lang in LANGS), key


@pytest.mark.parametrize("lang", LANGS)
def test_subject_carries_the_code_and_names_the_brand(lang):
    """El código se lee sin abrir el correo y se sabe de quién es."""
    subject = otp_subject(CODE, lang)
    assert subject.startswith(CODE)
    assert "KM0 LAB" in subject
    assert len(subject) <= 40  # entero en la lista de un móvil
    assert "{" not in subject
    assert otp_subject(CODE, None) == otp_subject(CODE, "es")


@pytest.mark.parametrize("lang", LANGS)
def test_text_says_code_where_to_type_it_how_long_and_what_if_not_you(lang):
    body = render_otp_text(code=CODE, minutes=10, lang=lang)
    assert f"\n    {CODE}\n" in body  # el código, solo en su línea
    for key in ("title", "intro", "validity", "not_you", "footer_signature"):
        assert _filled(key, lang) in body, key
    assert "10" in _filled("validity", lang)
    assert "${" not in body and "{code}" not in body and "{minutes}" not in body


@pytest.mark.parametrize("lang", LANGS)
def test_html_shows_the_code_big_and_in_one_piece(lang):
    body = render_otp_html(code="660111", minutes=10, lang=lang)
    assert f'<html lang="{lang}"' in body
    for key in ("title", "intro", "validity", "not_you", "footer_signature"):
        assert _in_html(_filled(key, lang)) in body, key
    # El código va seguido, en un solo elemento: al copiarlo se pegan seis
    # cifras, no seis celdas.
    match = re.search(r"font-size:(\d+)px[^>]*>660111</div>", body)
    assert match, "the code must be a single run of text"
    assert int(match.group(1)) >= 40
    # Nada queda sin rellenar.
    assert "${" not in body and "{code}" not in body and "{minutes}" not in body


def test_html_minutes_come_from_the_caller():
    body = render_otp_html(code=CODE, minutes=5, lang="es")
    assert _in_html(_filled("validity", "es", minutes=5)) in body
    assert "Caduca dentro de 5 minutos." in body


def test_html_previews_the_code_in_the_inbox():
    body = render_otp_html(code="660111", minutes=10, lang="es")
    hidden = body.split("display:none", 1)[1].split("</div>", 1)[0]
    assert "660111" in hidden


def test_html_keeps_the_brand_in_one_line_and_has_no_logo_image():
    """Cabecera en texto: no hay PNG público del logotipo original."""
    body = render_otp_html(code=CODE, minutes=10, lang="ca")
    assert ">KM0&nbsp;LAB</span>" in body
    assert "<img" not in body


def test_html_has_dark_mode_colours():
    body = render_otp_html(code=CODE, minutes=10, lang="ca")
    assert "prefers-color-scheme: dark" in body
    assert 'name="color-scheme" content="light dark"' in body


def test_the_email_does_not_show_the_address_it_was_sent_to():
    """Quien lo lee ya sabe cuál es su correo: no añade nada."""
    assert "a@b.com" not in render_otp_html(
        code="123456", minutes=10, lang="es", email="a@b.com"
    )
    assert "a@b.com" not in render_otp_text(
        code="123456", minutes=10, lang="es", email="a@b.com"
    )


def test_unknown_language_falls_back_to_spanish():
    assert render_otp_html(code=CODE, minutes=5, lang=None) == render_otp_html(
        code=CODE, minutes=5, lang="es"
    )
    assert render_otp_text(code=CODE, minutes=5, lang="fr") == render_otp_text(
        code=CODE, minutes=5, lang="es"
    )


def test_nothing_is_loaded_from_outside():
    """Sin imágenes, hojas de estilo ni enlaces: nada que el correo bloquee."""
    body = render_otp_html(code="123456", minutes=10, lang="ca")
    assert "src=" not in body and "href=" not in body and "url(" not in body
