"""The access-code email: copy and HTML/text render (app and backoffice).

One job: the person has to see the code, know where to type it and how long
it lasts. The subject carries the code (it is readable from the inbox list
and the notification, without opening the email) and the body shows it big
and as a single run of text, so copying it pastes six digits.

The design and the copy were approved on 2026-11-26 and live, with their
screenshots, in ``Docs/marketing/piloto/correo`` of the workspace. The HTML
below is that file as delivered: change it there first, then here.

The header is the words "KM0 LAB", not the logotype: mail programs do not
draw SVG and the only original of the logotype is an SVG. It needs a PNG
export of that original at a public address; until one exists, text.
"""

from __future__ import annotations

import html
from string import Template

from app.catalog.i18n import SUPPORTED_LANGS

# OTP emails default to Spanish when the user language is unknown.
OTP_DEFAULT_LANG = "es"

# In the texts, ``{code}`` and ``{minutes}`` are filled in.
OTP_COPY: dict[str, dict[str, str]] = {
    # The code first: it is what the inbox list and the notification show.
    "subject": {
        "ca": "{code} és el teu codi de KM0 LAB",
        "es": "{code} es tu código de KM0 LAB",
        "en": "{code} is your KM0 LAB code",
    },
    # The line the inbox shows next to the subject.
    "preheader": {
        "ca": "Escriu {code} a KM0 LAB per entrar. Caduca d'aquí a {minutes} minuts.",
        "es": "Escribe {code} en KM0 LAB para entrar. Caduca dentro de {minutes} minutos.",
        "en": "Enter {code} in KM0 LAB to sign in. It expires in {minutes} minutes.",
    },
    "title": {
        "ca": "El teu codi per entrar a KM0 LAB",
        "es": "Tu código para entrar en KM0 LAB",
        "en": "Your code to sign in to KM0 LAB",
    },
    "intro": {
        "ca": "Escriu aquest codi a KM0 LAB, a la pantalla on te'l demana:",
        "es": "Escribe este código en KM0 LAB, en la pantalla donde te lo pide:",
        "en": "Enter this code in KM0 LAB, on the screen that asks for it:",
    },
    "validity": {
        "ca": "Caduca d'aquí a {minutes} minuts.",
        "es": "Caduca dentro de {minutes} minutos.",
        "en": "It expires in {minutes} minutes.",
    },
    "not_you": {
        "ca": "Si no l'has demanat tu, ignora aquest correu: sense aquest codi ningú pot entrar al teu compte. No el comparteixis amb ningú.",
        "es": "Si no lo has pedido tú, ignora este correo: sin este código nadie puede entrar en tu cuenta. No lo compartas con nadie.",
        "en": "If you didn't ask for it, ignore this email: nobody can get into your account without this code. Don't share it with anyone.",
    },
    "footer_signature": {
        "ca": "KM0 LAB · Comerç local de proximitat",
        "es": "KM0 LAB · Comercio local de proximidad",
        "en": "KM0 LAB · Local neighbourhood commerce",
    },
}


# ``${name}`` placeholders: lang, code, and one per text above. Inline
# styles and tables because mail programs need them; the <style> block only
# adds the dark-mode colours for the programs that honour it.
_HTML = Template(
    """<!DOCTYPE html>
<html lang="${lang}" xmlns="http://www.w3.org/1999/xhtml">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="light dark">
<meta name="supported-color-schemes" content="light dark">
<title>${title}</title>
<style>
  :root { color-scheme: light dark; supported-color-schemes: light dark; }
  @media (prefers-color-scheme: dark) {
    .bg-page { background-color: #0E1B33 !important; }
    .bg-card { background-color: #16233F !important; border-color: #2A3B5E !important; }
    .bg-head { background-color: #F9D56E !important; }
    .bg-code { background-color: #0E1B33 !important; border-color: #6F95E8 !important; }
    .t-main { color: #F3F6FC !important; }
    .t-code { color: #FFFFFF !important; }
    .t-warn { color: #FFB4A6 !important; }
    .t-muted { color: #A9B6CF !important; }
    .t-head { color: #132A50 !important; }
    .bd-top { border-top-color: #2A3B5E !important; }
  }
</style>
</head>
<body class="bg-page" style="margin:0;padding:0;background-color:#FFF9F0;">
<div style="display:none;max-height:0;overflow:hidden;opacity:0;font-size:1px;line-height:1px;color:#FFF9F0;">${preheader}</div>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" class="bg-page" style="background-color:#FFF9F0;">
  <tr>
    <td align="center" style="padding:16px 12px;">
      <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" class="bg-card" style="width:100%;max-width:600px;background-color:#FFFFFF;border:1px solid #E6DCCB;border-radius:24px;">
        <tr>
          <td align="center" class="bg-head" style="background-color:#F9D56E;border-radius:23px 23px 0 0;padding:20px 16px;">
            <!-- PENDIENTE: logotipo original (PNG exportado del SVG original, en una URL publica). Mientras, el nombre en texto. -->
            <span class="t-head" style="font-family:Arial,Helvetica,sans-serif;font-size:24px;line-height:28px;font-weight:700;letter-spacing:1px;color:#164194;white-space:nowrap;">KM0&nbsp;LAB</span>
          </td>
        </tr>
        <tr>
          <td style="padding:28px 20px 8px 20px;" align="center">
            <h1 class="t-main" style="margin:0 0 8px 0;font-family:Arial,Helvetica,sans-serif;font-size:22px;line-height:28px;font-weight:700;color:#132A50;text-align:center;">${title}</h1>
            <p class="t-main" style="margin:0;font-family:Arial,Helvetica,sans-serif;font-size:16px;line-height:24px;color:#132A50;text-align:center;">${intro}</p>
          </td>
        </tr>
        <tr>
          <td style="padding:16px 16px 8px 16px;">
            <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" class="bg-code" style="background-color:#EEF3FC;border:2px solid #164194;border-radius:20px;">
              <tr>
                <td align="center" style="padding:22px 4px 20px 4px;">
                  <div class="t-code" style="margin:0;font-family:'Courier New',Courier,monospace;font-size:48px;line-height:54px;font-weight:700;letter-spacing:6px;color:#164194;text-align:center;white-space:nowrap;-webkit-user-select:all;user-select:all;">${code}</div>
                  <div class="t-warn" style="margin:12px 0 0 0;font-family:Arial,Helvetica,sans-serif;font-size:16px;line-height:22px;font-weight:700;color:#C2330F;text-align:center;">${validity}</div>
                </td>
              </tr>
            </table>
          </td>
        </tr>
        <tr>
          <td style="padding:12px 24px 28px 24px;" align="center">
            <p class="t-muted" style="margin:0;font-family:Arial,Helvetica,sans-serif;font-size:14px;line-height:21px;color:#5B6475;text-align:center;">${not_you}</p>
          </td>
        </tr>
        <tr>
          <td class="bd-top" align="center" style="border-top:1px solid #E6DCCB;padding:14px 16px;">
            <p class="t-muted" style="margin:0;font-family:Arial,Helvetica,sans-serif;font-size:12px;line-height:18px;color:#5B6475;text-align:center;">${footer_signature}</p>
          </td>
        </tr>
      </table>
    </td>
  </tr>
</table>
</body>
</html>
"""
)

_TEXT = Template(
    """${title}

${intro}

    ${code}

${validity}

${not_you}

${footer_signature}
"""
)


def normalize_otp_lang(value: str | None) -> str:
    lang = (value or "").strip().lower()
    return lang if lang in SUPPORTED_LANGS else OTP_DEFAULT_LANG


def _texts(lang: str, *, code: str, minutes: int) -> dict[str, str]:
    """Every text in ``lang`` with the code and the minutes filled in."""
    return {
        key: (row.get(lang) or row[OTP_DEFAULT_LANG])
        .replace("{code}", code)
        .replace("{minutes}", str(minutes))
        for key, row in OTP_COPY.items()
    }


def otp_subject(code: str, lang: str | None = None) -> str:
    row = OTP_COPY["subject"]
    L = normalize_otp_lang(lang)
    return (row.get(L) or row[OTP_DEFAULT_LANG]).replace("{code}", code)


def render_otp_text(
    *,
    code: str,
    minutes: int,
    lang: str | None = None,
    email: str | None = None,  # kept for callers; the email is not shown
) -> str:
    L = normalize_otp_lang(lang)
    return _TEXT.substitute(_texts(L, code=code, minutes=minutes), code=code)


def _html_text(value: str) -> str:
    """Escaped for a text node; the brand never breaks across two lines."""
    return html.escape(value, quote=False).replace("KM0 LAB", "KM0&nbsp;LAB")


def render_otp_html(
    *,
    code: str,
    minutes: int,
    lang: str | None = None,
    email: str | None = None,  # kept for callers; the email is not shown
) -> str:
    L = normalize_otp_lang(lang)
    texts = {
        key: _html_text(value)
        for key, value in _texts(L, code=code, minutes=minutes).items()
    }
    return _HTML.substitute(
        texts, lang=L, code=html.escape(code, quote=False), minutes=minutes
    )
