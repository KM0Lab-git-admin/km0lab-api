"""The email a shop gets when the administrator registers it.

Registering a shop with someone's email is the invitation (the first login
with that email takes the shop), but until now nothing told the shop: the
administrator had to. This email does: who we are, the three steps and one
button to the panel.

Copy and layout come from ``Docs/marketing/piloto/correo`` of the workspace
(``invitacion-comercio.json`` and ``invitacion-comercio.md``, 27-11-2026):
the same card as the access-code email, without the code box, with numbered
steps and one pill button. Change the texts there first, then here. In
Catalan, "cartell", "taulell" and "correu no desitjat" are the words of the
shop's printed sheet: keep them.

Variables: ``{shop_name}``, ``{town}``, ``{entity}`` and the panel address,
which is never written in the copy: it always arrives from configuration.
"""

from __future__ import annotations

import html
from string import Template

from app.catalog.i18n import SUPPORTED_LANGS

# Shops are told in the language of their municipality; Catalan if unknown.
INVITE_DEFAULT_LANG = "ca"

INVITE_COPY: dict[str, dict[str, str]] = {
    "ca": {
        "subject": "El teu comerç ja és a KM0 LAB",
        "preheader": "Ja pots entrar al panell amb aquest mateix correu.",
        "greeting": "Hola,",
        "intro": "Som KM0 LAB. El teu comerç, {shop_name}, ja està donat d'alta a {town}, a proposta de {entity}.",
        "intro_no_entity": "Som KM0 LAB. El teu comerç, {shop_name}, ja està donat d'alta a {town}.",
        "steps_title": "Què has de fer ara",
        "step1": "Entra al panell amb aquest mateix correu. T'arribarà un codi de 6 xifres: no hi ha contrasenya.",
        "step1_hint": "Si no veus el codi, mira a «correu no desitjat».",
        "step2": "Omple la teva fitxa: el logotip, l'horari i una oferta.",
        "step3": "Imprimeix el cartell amb el teu codi QR i posa'l al taulell.",
        "gain": "Els veïns escanegen el teu codi quan entren al comerç i sumen punts. Durant el pilot no et costa res.",
        "button": "Entrar al panell",
        "help": "Cap dubte? Escriu-nos a info@km0lab.com.",
        "footer_signature": "KM0 LAB",
    },
    "es": {
        "subject": "Tu comercio ya está en KM0 LAB",
        "preheader": "Ya puedes entrar en el panel con este mismo correo.",
        "greeting": "Hola,",
        "intro": "Somos KM0 LAB. Tu comercio, {shop_name}, ya está dado de alta en {town}, a propuesta de {entity}.",
        "intro_no_entity": "Somos KM0 LAB. Tu comercio, {shop_name}, ya está dado de alta en {town}.",
        "steps_title": "Qué tienes que hacer ahora",
        "step1": "Entra en el panel con este mismo correo. Te llegará un código de 6 cifras: no hay contraseña.",
        "step1_hint": "Si no ves el código, mira en «correo no deseado».",
        "step2": "Completa tu ficha: el logotipo, el horario y una oferta.",
        "step3": "Imprime el cartel con tu código QR y ponlo en el mostrador.",
        "gain": "Los vecinos escanean tu código al entrar en el comercio y suman puntos. Durante el piloto no te cuesta nada.",
        "button": "Entrar en el panel",
        "help": "¿Alguna duda? Escríbenos a info@km0lab.com.",
        "footer_signature": "KM0 LAB",
    },
    "en": {
        "subject": "Your shop is now on KM0 LAB",
        "preheader": "You can now sign in to the panel with this same email.",
        "greeting": "Hello,",
        "intro": "We're KM0 LAB. Your shop, {shop_name}, has been added in {town}, at the suggestion of {entity}.",
        "intro_no_entity": "We're KM0 LAB. Your shop, {shop_name}, has been added in {town}.",
        "steps_title": "What to do now",
        "step1": "Sign in to the panel with this same email. You'll get a 6-digit code: there is no password.",
        "step1_hint": "If you don't see the code, check your spam folder.",
        "step2": "Fill in your profile: logo, opening hours and an offer.",
        "step3": "Print the poster with your QR code and put it on the counter.",
        "gain": "Neighbours scan your code when they come into the shop and earn points. During the pilot it costs you nothing.",
        "button": "Go to the panel",
        "help": "Any questions? Write to us at info@km0lab.com.",
        "footer_signature": "KM0 LAB",
    },
}

_STEP = Template(
    """              <tr>
                <td valign="top" width="36" style="padding:0 0 14px 0;">
                  <div class="bg-num" style="width:28px;height:28px;border-radius:14px;background-color:#164194;color:#FFFFFF;font-family:Arial,Helvetica,sans-serif;font-size:15px;line-height:28px;font-weight:700;text-align:center;">${number}</div>
                </td>
                <td valign="top" style="padding:2px 0 14px 0;">
                  <p class="t-main" style="margin:0;font-family:Arial,Helvetica,sans-serif;font-size:16px;line-height:24px;color:#132A50;">${text}</p>${hint}
                </td>
              </tr>
"""
)

_HINT = Template(
    """
                  <p class="t-muted" style="margin:4px 0 0 0;font-family:Arial,Helvetica,sans-serif;font-size:14px;line-height:20px;color:#5B6475;">${text}</p>"""
)

# The shell (head, yellow header, footer, dark mode) is the access-code
# email's, as approved; only the body between header and footer differs.
_HTML = Template(
    """<!DOCTYPE html>
<html lang="${lang}" xmlns="http://www.w3.org/1999/xhtml">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="light dark">
<meta name="supported-color-schemes" content="light dark">
<title>${subject}</title>
<style>
  :root { color-scheme: light dark; supported-color-schemes: light dark; }
  @media (prefers-color-scheme: dark) {
    .bg-page { background-color: #0E1B33 !important; }
    .bg-card { background-color: #16233F !important; border-color: #2A3B5E !important; }
    .bg-head { background-color: #F9D56E !important; }
    .bg-num { background-color: #6F95E8 !important; color: #0E1B33 !important; }
    .bg-btn { background-color: #6F95E8 !important; }
    .t-btn { color: #0E1B33 !important; }
    .t-main { color: #F3F6FC !important; }
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
          <td style="padding:28px 24px 4px 24px;">
            <p class="t-main" style="margin:0 0 12px 0;font-family:Arial,Helvetica,sans-serif;font-size:16px;line-height:24px;color:#132A50;">${greeting}</p>
            <p class="t-main" style="margin:0;font-family:Arial,Helvetica,sans-serif;font-size:16px;line-height:24px;color:#132A50;">${intro}</p>
          </td>
        </tr>
        <tr>
          <td style="padding:20px 24px 0 24px;">
            <h1 class="t-main" style="margin:0 0 14px 0;font-family:Arial,Helvetica,sans-serif;font-size:20px;line-height:26px;font-weight:700;color:#132A50;">${steps_title}</h1>
            <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">
${steps}            </table>
          </td>
        </tr>
        <tr>
          <td style="padding:4px 24px 0 24px;">
            <p class="t-main" style="margin:0;font-family:Arial,Helvetica,sans-serif;font-size:16px;line-height:24px;color:#132A50;">${gain}</p>
          </td>
        </tr>
        <tr>
          <td align="center" style="padding:24px 24px 8px 24px;">
            <a class="bg-btn t-btn" href="${panel_url}" style="display:block;box-sizing:border-box;width:100%;min-height:48px;padding:14px 20px;border-radius:999px;background-color:#164194;color:#FFFFFF;font-family:Arial,Helvetica,sans-serif;font-size:16px;line-height:20px;font-weight:700;text-align:center;text-decoration:none;">${button}</a>
          </td>
        </tr>
        <tr>
          <td style="padding:12px 24px 28px 24px;" align="center">
            <p class="t-muted" style="margin:0;font-family:Arial,Helvetica,sans-serif;font-size:14px;line-height:21px;color:#5B6475;text-align:center;">${help}</p>
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
    """${subject}

${greeting}

${intro}

${steps_title}
1. ${step1}
   ${step1_hint}
2. ${step2}
3. ${step3}

${gain}

${button}: ${panel_url}

${help}

${footer_signature}
"""
)


def normalize_invite_lang(value: str | None) -> str:
    lang = (value or "").strip().lower()
    return lang if lang in SUPPORTED_LANGS else INVITE_DEFAULT_LANG


def _texts(lang: str, *, shop_name: str, town: str, entity: str | None) -> dict[str, str]:
    """Every text in ``lang``, with the intro chosen and its names filled in."""
    copy = dict(INVITE_COPY[lang])
    entity = (entity or "").strip()
    intro = copy.pop("intro") if entity else copy["intro_no_entity"]
    copy.pop("intro_no_entity", None)
    copy["intro"] = (
        intro.replace("{shop_name}", shop_name.strip())
        .replace("{town}", town.strip())
        .replace("{entity}", entity)
    )
    return copy


def shop_invite_subject(lang: str | None = None) -> str:
    return INVITE_COPY[normalize_invite_lang(lang)]["subject"]


def render_shop_invite_text(
    *,
    shop_name: str,
    town: str,
    entity: str | None,
    panel_url: str,
    lang: str | None = None,
) -> str:
    L = normalize_invite_lang(lang)
    return _TEXT.substitute(
        _texts(L, shop_name=shop_name, town=town, entity=entity), panel_url=panel_url
    )


def _html_text(value: str) -> str:
    """Escaped for a text node; the brand never breaks across two lines."""
    return html.escape(value, quote=False).replace("KM0 LAB", "KM0&nbsp;LAB")


def render_shop_invite_html(
    *,
    shop_name: str,
    town: str,
    entity: str | None,
    panel_url: str,
    lang: str | None = None,
) -> str:
    L = normalize_invite_lang(lang)
    texts = {
        key: _html_text(value)
        for key, value in _texts(
            L, shop_name=shop_name, town=town, entity=entity
        ).items()
    }
    steps = "".join(
        _STEP.substitute(
            number=number,
            text=texts[key],
            hint=_HINT.substitute(text=texts[hint]) if hint else "",
        )
        for number, key, hint in (
            (1, "step1", "step1_hint"),
            (2, "step2", None),
            (3, "step3", None),
        )
    )
    return _HTML.substitute(
        texts,
        lang=L,
        steps=steps,
        panel_url=html.escape(panel_url, quote=True),
    )
