"""OTP email copy + HTML/text render (shared app + backoffice).

Mirrors Lovable ``EmailOtpTemplate`` / ``email_otp.*`` i18n keys.
Brand mark is plain text ``KM0 LAB`` until a logo asset is wired.
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
_DIGIT_BORDER = "rgba(23, 64, 148, 0.20)"

OTP_COPY: dict[str, dict[str, str]] = {
    "subject": {
        "ca": "El teu codi d'accés a KM0 LAB",
        "es": "Tu código de acceso a KM0 LAB",
        "en": "Your KM0 LAB access code",
    },
    "title": {
        "ca": "El teu codi d'accés",
        "es": "Tu código de acceso",
        "en": "Your access code",
    },
    "intro": {
        "ca": "Fes servir aquest codi per entrar a KM0 LAB o recuperar la teva sessió.",
        "es": "Usa este código para entrar en KM0 LAB o recuperar tu sesión.",
        "en": "Use this code to sign in to KM0 LAB or recover your session.",
    },
    "code_label": {
        "ca": "Codi de 6 dígits",
        "es": "Código de 6 dígitos",
        "en": "6-digit code",
    },
    "validity": {
        "ca": "Vàlid durant {minutes} minuts",
        "es": "Válido durante {minutes} minutos",
        "en": "Valid for {minutes} minutes",
    },
    "security": {
        "ca": (
            "Si no has demanat aquest codi, ignora aquest correu. "
            "No el comparteixis amb ningú."
        ),
        "es": (
            "Si no has pedido este código, ignora este correo. "
            "No lo compartas con nadie."
        ),
        "en": "If you didn't request this code, ignore this email. Never share it.",
    },
    "footer_hint": {
        "ca": "No el trobes a la safata d'entrada? Mira a spam o promocions.",
        "es": "¿No lo encuentras en la bandeja de entrada? Mira en spam o promociones.",
        "en": "Can't find it in your inbox? Check spam or promotions.",
    },
    "footer_signature": {
        "ca": "KM0 LAB · Comerç local de proximitat",
        "es": "KM0 LAB · Comercio local de proximidad",
        "en": "KM0 LAB · Local neighbourhood commerce",
    },
    "greeting": {
        "ca": "Hola!",
        "es": "¡Hola!",
        "en": "Hi!",
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


def otp_subject(lang: str | None = None) -> str:
    return _t("subject", normalize_otp_lang(lang))


def render_otp_text(
    *,
    code: str,
    minutes: int,
    lang: str | None = None,
    email: str | None = None,
) -> str:
    L = normalize_otp_lang(lang)
    lines = [
        _t("greeting", L),
        "",
        _t("intro", L),
    ]
    if email:
        lines.append(email)
    lines.extend(
        [
            "",
            f"{_t('code_label', L)}: {code}",
            _t("validity", L, minutes=minutes),
            "",
            _t("security", L),
            "",
            _t("footer_hint", L),
            _t("footer_signature", L),
        ]
    )
    return "\n".join(lines)


def _digit_cells(code: str) -> str:
    digits = ("".join(c for c in code if c.isdigit()) + "000000")[:6]
    cells: list[str] = []
    for d in digits:
        cells.append(
            (
                '<td style="width:36px;height:44px;border-radius:8px;'
                f'background:{_WHITE};border:1px solid {_DIGIT_BORDER};'
                f'color:{_BLUE_700};font-family:Arial,Helvetica,sans-serif;'
                'font-size:20px;font-weight:700;text-align:center;'
                'vertical-align:middle;letter-spacing:0;">'
                f"{html.escape(d)}</td>"
            )
        )
    return (
        '<table role="presentation" cellpadding="0" cellspacing="0" '
        'style="margin:0 auto;border-collapse:separate;border-spacing:8px 0;">'
        f"<tr>{''.join(cells)}</tr></table>"
    )


def render_otp_html(
    *,
    code: str,
    minutes: int,
    lang: str | None = None,
    email: str | None = None,
) -> str:
    """Table-based HTML matching Lovable EmailOtpTemplate layout."""
    L = normalize_otp_lang(lang)
    title = html.escape(_t("title", L))
    intro = html.escape(_t("intro", L))
    code_label = html.escape(_t("code_label", L))
    validity = html.escape(_t("validity", L, minutes=minutes))
    security = html.escape(_t("security", L))
    footer_hint = html.escape(_t("footer_hint", L))
    footer_sig = html.escape(_t("footer_signature", L))
    email_row = ""
    if email:
        email_row = (
            f'<p style="margin:0;font-family:Arial,Helvetica,sans-serif;'
            f'font-size:14px;line-height:1.4;color:{_BLUE_800};'
            f'word-break:break-all;">{html.escape(email)}</p>'
        )

    return f"""<!DOCTYPE html>
<html lang="{html.escape(L)}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title>
</head>
<body style="margin:0;padding:0;background:{_BEIGE_100};">
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
          <td style="padding:28px 24px;">
            <h1 style="margin:0 0 8px;font-family:Georgia,'Times New Roman',serif;
              font-size:24px;line-height:1.25;color:{_BLUE_700};font-weight:700;">
              {title}
            </h1>
            <p style="margin:0 0 8px;font-family:Arial,Helvetica,sans-serif;
              font-size:14px;line-height:1.5;color:{_MUTED};">
              {intro}
            </p>
            {email_row}
            <table role="presentation" width="100%" cellpadding="0" cellspacing="0"
              style="margin:20px 0;border:2px solid {_BORDER};border-radius:16px;
              background:rgba(255,236,210,0.6);">
              <tr>
                <td align="center" style="padding:20px 16px;">
                  <p style="margin:0 0 12px;font-family:Arial,Helvetica,sans-serif;
                    font-size:12px;line-height:1.3;letter-spacing:0.06em;
                    text-transform:uppercase;color:{_MUTED};">
                    {code_label}
                  </p>
                  {_digit_cells(code)}
                  <p style="margin:12px 0 0;font-family:Arial,Helvetica,sans-serif;
                    font-size:14px;line-height:1.4;font-weight:700;
                    color:{_CORAL_400};text-align:center;">
                    {validity}
                  </p>
                </td>
              </tr>
            </table>
            <p style="margin:0;font-family:Arial,Helvetica,sans-serif;
              font-size:14px;line-height:1.5;color:{_MUTED};">
              {security}
            </p>
          </td>
        </tr>
        <tr>
          <td style="border-top:1px solid #E5E7EB;padding:16px 24px;">
            <p style="margin:0 0 4px;font-family:Arial,Helvetica,sans-serif;
              font-size:12px;line-height:1.4;color:{_MUTED};text-align:center;">
              {footer_hint}
            </p>
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
