"""The access-code email: subject, text and HTML."""

import html as html_lib
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


def test_normalize_otp_lang_defaults_to_spanish():
    assert OTP_DEFAULT_LANG == "es"
    assert normalize_otp_lang(None) == "es"
    assert normalize_otp_lang("") == "es"
    assert normalize_otp_lang("fr") == "es"
    assert normalize_otp_lang("CA") == "ca"
    assert normalize_otp_lang("es") == "es"
    assert normalize_otp_lang("en") == "en"


def test_every_text_exists_in_the_three_languages():
    for key, row in OTP_COPY.items():
        assert set(row) == set(LANGS), key
        assert all(row[lang].strip() for lang in LANGS), key


@pytest.mark.parametrize("lang", LANGS)
def test_subject_names_the_brand_and_carries_the_code(lang):
    """Se reconoce en la bandeja y el código se lee sin abrir el correo."""
    subject = otp_subject("482913", lang)
    assert subject.startswith("KM0 LAB")
    assert "482913" in subject
    assert len(subject) <= 40  # entero en la lista de un móvil
    assert otp_subject("482913", None) == otp_subject("482913", "es")


@pytest.mark.parametrize("lang", LANGS)
def test_text_says_code_where_to_type_it_how_long_and_what_if_not_you(lang):
    body = render_otp_text(code="482913", minutes=10, lang=lang)
    assert "482913" in body
    assert OTP_COPY["intro"][lang] in body
    assert OTP_COPY["validity"][lang].format(minutes=10) in body
    assert OTP_COPY["not_you"][lang] in body
    assert "KM0 LAB" in body


@pytest.mark.parametrize("lang", LANGS)
def test_html_shows_the_code_big_and_in_one_piece(lang):
    body = render_otp_html(code="660111", minutes=10, lang=lang)
    assert f'lang="{lang}"' in body
    assert html_lib.escape(OTP_COPY["title"][lang]) in body
    # En el cuerpo, la marca no se parte en dos líneas.
    assert "KM0&nbsp;LAB" in body
    assert html_lib.escape(OTP_COPY["validity"][lang].format(minutes=10)) in body
    assert html_lib.escape(OTP_COPY["not_you"][lang]) in body
    # El código va seguido, en un solo elemento: al copiarlo se pegan seis
    # cifras, no seis celdas.
    match = re.search(r"font-size:(\d+)px[^>]*>660111</p>", body, re.S)
    assert match, "the code must be a single run of text"
    assert int(match.group(1)) >= 40


def test_html_previews_the_code_in_the_inbox():
    body = render_otp_html(code="660111", minutes=10, lang="es")
    hidden = body.split("display:none", 1)[1].split("</div>", 1)[0]
    assert "660111" in hidden


def test_the_email_does_not_show_the_address_it_was_sent_to():
    """Quien lo lee ya sabe cuál es su correo: no añade nada."""
    assert "a@b.com" not in render_otp_html(
        code="123456", minutes=10, lang="es", email="a@b.com"
    )
    assert "a@b.com" not in render_otp_text(
        code="123456", minutes=10, lang="es", email="a@b.com"
    )


def test_unknown_language_falls_back_to_spanish():
    body = render_otp_html(code="999999", minutes=5, lang=None)
    assert html_lib.escape(OTP_COPY["title"]["es"]) in body
    assert html_lib.escape(OTP_COPY["validity"]["es"].format(minutes=5)) in body


def test_no_remote_resources():
    """Sin imágenes ni hojas de estilo de fuera: nada que el correo bloquee."""
    body = render_otp_html(code="123456", minutes=10, lang="ca")
    assert "<img" not in body
    assert "http://" not in body and "https://" not in body
