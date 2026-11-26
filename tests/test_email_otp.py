"""Unit tests for OTP email HTML/text template."""

from app.catalog.email_otp import (
    OTP_COPY,
    OTP_DEFAULT_LANG,
    normalize_otp_lang,
    otp_subject,
    render_otp_html,
    render_otp_text,
)


def test_normalize_otp_lang_defaults_to_spanish():
    assert OTP_DEFAULT_LANG == "es"
    assert normalize_otp_lang(None) == "es"
    assert normalize_otp_lang("") == "es"
    assert normalize_otp_lang("fr") == "es"
    assert normalize_otp_lang("CA") == "ca"
    assert normalize_otp_lang("es") == "es"
    assert normalize_otp_lang("en") == "en"


def test_otp_subject_localized():
    assert otp_subject("es") == OTP_COPY["subject"]["es"]
    assert otp_subject("ca") == OTP_COPY["subject"]["ca"]
    assert otp_subject("en") == OTP_COPY["subject"]["en"]
    assert otp_subject(None) == otp_subject("es")


def test_render_otp_text_includes_code_and_minutes():
    body = render_otp_text(code="123456", minutes=10, lang="es", email="a@b.com")
    assert "123456" in body
    assert "10" in body
    assert "a@b.com" in body
    assert "KM0 LAB" in body


def test_render_otp_html_matches_template_shape():
    import html as html_lib

    body = render_otp_html(code="660111", minutes=10, lang="ca", email="hola@km0lab.com")
    assert "KM0 LAB" in body
    assert html_lib.escape(OTP_COPY["title"]["ca"]) in body
    for digit in "660111":
        assert f">{digit}</td>" in body
    assert "hola@km0lab.com" in body
    assert html_lib.escape(OTP_COPY["validity"]["ca"].format(minutes=10)) in body
    assert 'lang="ca"' in body


def test_render_otp_html_defaults_unknown_lang_to_es():
    import html as html_lib

    body = render_otp_html(code="999999", minutes=5, lang=None)
    assert html_lib.escape(OTP_COPY["title"]["es"]) in body
    assert html_lib.escape(OTP_COPY["validity"]["es"].format(minutes=5)) in body
