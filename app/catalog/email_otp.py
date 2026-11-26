"""The access-code email: copy and HTML/text render (app and backoffice).

One job: the person has to see the code, know where to type it and how long
it lasts. So the subject carries the code (it is readable from the inbox
list and the notification, without opening the email), the body shows it
big and as a single run of text (copying it pastes six digits, not six
cells), and nothing else competes with it.

The header is the words "KM0 LAB" on the brand blue, not the logotype: mail
programs do not draw SVG, and the only original of the logotype is an SVG.
Putting the logotype here needs a PNG export of that original, served from
a public address; until one exists the text stays.
"""

from __future__ import annotations

import html
from typing import Any

from app.catalog.i18n import SUPPORTED_LANGS

# OTP emails default to Spanish when the user language is unknown.
OTP_DEFAULT_LANG = "es"

# Brand colours (hex) from Lovable tokens — inline styles only (email-safe).
_BLUE_700 = "#174094"
_BLUE_800 = "#132A50"
_BEIGE_50 = "#FFF9F0"
_BEIGE_100 = "#FFECD2"
_CORAL_400 = "#FF664D"
_MUTED = "#6B7280"
_WHITE = "#FFFFFF"
_BORDER = "rgba(23, 64, 148, 0.15)"

OTP_COPY: dict[str, dict[str, str]] = {
    # Brand first, so the sender is recognised; then the code.
    "subject": {
        "ca": "KM0 LAB: {code} és el teu codi",
        "es": "KM0 LAB: {code} es tu código",
        "en": "KM0 LAB: {code} is your code",
    },
    "title": {
        "ca": "El teu codi per entrar a KM0 LAB",
        "es": "Tu código para entrar en KM0 LAB",
        "en": "Your code to sign in to KM0 LAB",
    },
    "intro": {
        "ca": "Escriu aquest codi a KM0 LAB, a la pantalla on te'l demana:",
        "es": "Escribe este código en KM0 LAB, en la pantalla donde te lo pide:",
        "en": "Type this code in KM0 LAB, on the screen that asks for it:",
    },
    "validity": {
        "ca": "Caduca d'aquí a {minutes} minuts.",
        "es": "Caduca dentro de {minutes} minutos.",
        "en": "It expires in {minutes} minutes.",
    },
    "not_you": {
        "ca": (
            "No l'has demanat tu? No cal que facis res: sense aquest codi "
            "ningú pot entrar al teu compte. No el comparteixis amb ningú."
        ),
        "es": (
            "¿No lo has pedido tú? No hace falta que hagas nada: sin este "
            "código nadie puede entrar en tu cuenta. No lo compartas con nadie."
        ),
        "en": (
            "Didn't ask for it? You don't need to do anything: nobody can get "
            "into your account without this code. Don't share it with anyone."
        ),
    },
    "footer_signature": {
        "ca": "KM0 LAB · Comerç local de proximitat",
        "es": "KM0 LAB · Comercio local de proximidad",
        "en": "KM0 LAB · Local neighbourhood commerce",
    },
}


def normalize_otp_lang(value: str | None) -> str:
    lang = (value or "").strip().lower()
    return lang if lang in SUPPORTED_LANGS else OTP_DEFAULT_LANG


def _t(key: str, lang: str, **kwargs: Any) -> str:
    row = OTP_COPY[key]
    text = row.get(lang) or row[OTP_DEFAULT_LANG]
    if kwargs:
        return text.format(**kwargs)
    return text


def otp_subject(code: str, lang: str | None = None) -> str:
    return _t("subject", normalize_otp_lang(lang), code=code)


def render_otp_text(
    *,
    code: str,
    minutes: int,
    lang: str | None = None,
    email: str | None = None,  # kept for callers; the email is not shown
) -> str:
    L = normalize_otp_lang(lang)
    return "\n".join(
        [
            _t("title", L),
            "",
            _t("intro", L),
            "",
            f"    {code}",
            "",
            _t("validity", L, minutes=minutes),
            "",
            _t("not_you", L),
            "",
            _t("footer_signature", L),
        ]
    )


def render_otp_html(
    *,
    code: str,
    minutes: int,
    lang: str | None = None,
    email: str | None = None,  # kept for callers; the email is not shown
) -> str:
    """Table-based HTML with inline styles, as mail programs need."""
    L = normalize_otp_lang(lang)
    # The brand never breaks across two lines.
    title = html.escape(_t("title", L)).replace("KM0 LAB", "KM0&nbsp;LAB")
    intro = html.escape(_t("intro", L)).replace("KM0 LAB", "KM0&nbsp;LAB")
    validity = html.escape(_t("validity", L, minutes=minutes))
    not_you = html.escape(_t("not_you", L))
    footer_sig = html.escape(_t("footer_signature", L))
    shown_code = html.escape(code)
    # What the inbox shows next to the subject.
    preview = html.escape(f"{_t('intro', L)} {code}. {_t('validity', L, minutes=minutes)}")

    return f"""<!DOCTYPE html>
<html lang="{html.escape(L)}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(_t("title", L))}</title>
</head>
<body style="margin:0;padding:0;background:{_BEIGE_100};">
<div style="display:none;max-height:0;overflow:hidden;opacity:0;
  font-size:1px;line-height:1px;color:{_BEIGE_100};">
  {preview}
</div>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0"
  style="background:{_BEIGE_100};padding:32px 16px;">
  <tr>
    <td align="center">
      <table role="presentation" width="100%" cellpadding="0" cellspacing="0"
        style="max-width:480px;background:{_WHITE};border-radius:16px;
        overflow:hidden;border:1px solid {_BORDER};">
        <tr>
          <td align="center"
            style="background:{_BLUE_700};padding:20px 24px;">
            <span style="font-family:Arial,Helvetica,sans-serif;font-size:20px;
              font-weight:700;letter-spacing:0.04em;color:{_WHITE};">
              KM0 LAB
            </span>
          </td>
        </tr>
        <tr>
          <td style="padding:28px 24px 24px;">
            <h1 style="margin:0 0 12px;font-family:Arial,Helvetica,sans-serif;
              font-size:22px;line-height:1.3;color:{_BLUE_700};font-weight:700;">
              {title}
            </h1>
            <p style="margin:0;font-family:Arial,Helvetica,sans-serif;
              font-size:16px;line-height:1.5;color:{_BLUE_800};">
              {intro}
            </p>
            <table role="presentation" width="100%" cellpadding="0" cellspacing="0"
              style="margin:20px 0;border:2px solid {_BORDER};border-radius:16px;
              background:{_BEIGE_50};">
              <tr>
                <td align="center" style="padding:24px 12px 20px;">
                  <p style="margin:0;font-family:'Courier New',Courier,monospace;
                    font-size:44px;line-height:1.1;font-weight:700;
                    letter-spacing:8px;color:{_BLUE_700};text-align:center;
                    white-space:nowrap;">{shown_code}</p>
                  <p style="margin:14px 0 0;font-family:Arial,Helvetica,sans-serif;
                    font-size:15px;line-height:1.4;font-weight:700;
                    color:{_CORAL_400};text-align:center;">
                    {validity}
                  </p>
                </td>
              </tr>
            </table>
            <p style="margin:0;font-family:Arial,Helvetica,sans-serif;
              font-size:14px;line-height:1.5;color:{_MUTED};">
              {not_you}
            </p>
          </td>
        </tr>
        <tr>
          <td style="border-top:1px solid #E5E7EB;padding:16px 24px;">
            <p style="margin:0;font-family:Arial,Helvetica,sans-serif;
              font-size:12px;line-height:1.4;color:{_MUTED};text-align:center;">
              {footer_sig}
            </p>
          </td>
        </tr>
      </table>
    </td>
  </tr>
</table>
</body>
</html>
"""
