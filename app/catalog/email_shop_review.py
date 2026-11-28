"""Emails of a shop's request to join: received, approved, rejected, and
the notice to the administrator who has to validate it.

Copy comes from ``Docs/marketing/piloto/correo/validacion-comercio.json`` of
the workspace (the Correo chat, 27-11-2026). Change the texts there first,
then here. One correction on the way in: the Catalan preheader of the
rejection said "Et expliquem"; it is "T'expliquem".

Same card as the access-code and shop-invite emails (yellow header with
"KM0 LAB", dark mode, text only). Each email is a greeting and, in this
order and only if its copy has them: intro, the reason as a quote, body,
next, numbered steps, gain, one pill button and a help line.

Variables: ``{shop_name}``, ``{town}``, ``{reason}`` and the panel address.
The reason is written by the administrator: it is escaped and never
translated. The panel address is never in the copy.
"""

from __future__ import annotations

import html
from string import Template

from app.catalog.email_shop_invite import normalize_invite_lang

RECEIVED = "request_received"
APPROVED = "approved"
REJECTED = "rejected"
ADMIN_NEW = "admin_new_request"

REVIEW_COPY: dict[str, dict[str, dict[str, str]]] = {
    "ca": {
        RECEIVED: {
            "subject": "Hem rebut la teva sol·licitud",
            "preheader": "La revisarem abans de publicar res.",
            "greeting": "Hola,",
            "intro": "Som KM0 LAB. Hem rebut la teva sol·licitud d'alta per al comerç {shop_name}, a {town}.",
            "body": "La revisarem abans de publicar res. Fins que l'aprovem, el comerç no es veu a l'App. És possible que et truquem per comprovar les dades.",
            "next": "Quan ho tinguem, t'escriurem a aquest mateix correu.",
            "help": "Cap dubte? Escriu-nos a info@km0lab.com.",
            "footer_signature": "KM0 LAB",
        },
        APPROVED: {
            "subject": "El teu comerç ja és a KM0 LAB",
            "preheader": "Hem aprovat l'alta. Ja pots entrar al panell.",
            "greeting": "Hola,",
            "intro": "Bones notícies: hem aprovat l'alta del teu comerç, {shop_name}, a {town}. Ja és a KM0 LAB.",
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
        REJECTED: {
            "subject": "No hem pogut validar el teu comerç",
            "preheader": "T'expliquem el motiu.",
            "greeting": "Hola,",
            "intro": "Som KM0 LAB. No hem pogut validar l'alta del teu comerç, {shop_name}, a {town}.",
            "reason_label": "El motiu:",
            "body": "Si creus que és un error o vols aclarir-ho, escriu-nos a info@km0lab.com. Si no, esborrarem les dades que ens vas enviar en 30 dies.",
            "footer_signature": "KM0 LAB",
        },
        ADMIN_NEW: {
            "subject": "Nova sol·licitud de comerç: {shop_name}",
            "preheader": "{shop_name}, a {town}, espera la teva validació.",
            "greeting": "Hola,",
            "intro": "{shop_name}, a {town}, ha demanat l'alta a KM0 LAB.",
            "body": "Abans d'aprovar-la, truca al comerç: comprova que existeix i que qui demana l'alta el representa.",
            "button": "Veure la sol·licitud",
            "help": "Cap dubte? Escriu-nos a info@km0lab.com.",
            "footer_signature": "KM0 LAB",
        },
    },
    "es": {
        RECEIVED: {
            "subject": "Hemos recibido tu solicitud",
            "preheader": "La revisaremos antes de publicar nada.",
            "greeting": "Hola,",
            "intro": "Somos KM0 LAB. Hemos recibido tu solicitud de alta para el comercio {shop_name}, en {town}.",
            "body": "La revisaremos antes de publicar nada. Hasta que la aprobemos, el comercio no se ve en la App. Es posible que te llamemos para comprobar los datos.",
            "next": "Cuando lo tengamos, te escribiremos a este mismo correo.",
            "help": "¿Alguna duda? Escríbenos a info@km0lab.com.",
            "footer_signature": "KM0 LAB",
        },
        APPROVED: {
            "subject": "Tu comercio ya está en KM0 LAB",
            "preheader": "Hemos aprobado el alta. Ya puedes entrar en el panel.",
            "greeting": "Hola,",
            "intro": "Buenas noticias: hemos aprobado el alta de tu comercio, {shop_name}, en {town}. Ya está en KM0 LAB.",
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
        REJECTED: {
            "subject": "No hemos podido validar tu comercio",
            "preheader": "Te explicamos el motivo.",
            "greeting": "Hola,",
            "intro": "Somos KM0 LAB. No hemos podido validar el alta de tu comercio, {shop_name}, en {town}.",
            "reason_label": "El motivo:",
            "body": "Si crees que es un error o quieres aclararlo, escríbenos a info@km0lab.com. Si no, borraremos los datos que nos enviaste en 30 días.",
            "footer_signature": "KM0 LAB",
        },
        ADMIN_NEW: {
            "subject": "Nueva solicitud de comercio: {shop_name}",
            "preheader": "{shop_name}, en {town}, espera tu validación.",
            "greeting": "Hola,",
            "intro": "{shop_name}, en {town}, ha pedido el alta en KM0 LAB.",
            "body": "Antes de aprobarla, llama al comercio: comprueba que existe y que quien pide el alta lo representa.",
            "button": "Ver la solicitud",
            "help": "¿Alguna duda? Escríbenos a info@km0lab.com.",
            "footer_signature": "KM0 LAB",
        },
    },
    "en": {
        RECEIVED: {
            "subject": "We've received your request",
            "preheader": "We'll review it before publishing anything.",
            "greeting": "Hello,",
            "intro": "We're KM0 LAB. We've received your request to add the shop {shop_name}, in {town}.",
            "body": "We'll review it before publishing anything. Until we approve it, the shop is not shown in the App. We may call you to check the details.",
            "next": "When we're done, we'll write to you at this same email.",
            "help": "Any questions? Write to us at info@km0lab.com.",
            "footer_signature": "KM0 LAB",
        },
        APPROVED: {
            "subject": "Your shop is now on KM0 LAB",
            "preheader": "We've approved your registration. You can now sign in to the panel.",
            "greeting": "Hello,",
            "intro": "Good news: we've approved the registration of your shop, {shop_name}, in {town}. It's now on KM0 LAB.",
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
        REJECTED: {
            "subject": "We couldn't validate your shop",
            "preheader": "Here is the reason.",
            "greeting": "Hello,",
            "intro": "We're KM0 LAB. We couldn't validate the registration of your shop, {shop_name}, in {town}.",
            "reason_label": "The reason:",
            "body": "If you think this is a mistake or want to clear it up, write to us at info@km0lab.com. Otherwise, we'll delete the data you sent us within 30 days.",
            "footer_signature": "KM0 LAB",
        },
        ADMIN_NEW: {
            "subject": "New shop request: {shop_name}",
            "preheader": "{shop_name}, in {town}, is waiting for your approval.",
            "greeting": "Hello,",
            "intro": "{shop_name}, in {town}, has asked to join KM0 LAB.",
            "body": "Before approving it, call the shop: check that it exists and that whoever asked represents it.",
            "button": "View the request",
            "help": "Any questions? Write to us at info@km0lab.com.",
            "footer_signature": "KM0 LAB",
        },
    },
}

_P_STYLE = "font-family:Arial,Helvetica,sans-serif;font-size:16px;line-height:24px;color:#132A50;"

_PARAGRAPH = Template(
    '            <p class="t-main" style="margin:0 0 12px 0;' + _P_STYLE + '">${text}</p>\n'
)
# The reason, set apart as a quote: a bar on the left, no box, no button.
_REASON = Template(
    """            <p class="t-muted" style="margin:8px 0 6px 0;font-family:Arial,Helvetica,sans-serif;font-size:14px;line-height:20px;color:#5B6475;">${label}</p>
            <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="margin:0 0 16px 0;">
              <tr>
                <td style="border-left:4px solid #F9D56E;padding:2px 0 2px 14px;">
                  <p class="t-main" style="margin:0;"""
    + _P_STYLE
    + """word-break:break-word;">${reason}</p>
                </td>
              </tr>
            </table>
"""
)
_STEPS_TITLE = Template(
    """            <h1 class="t-main" style="margin:8px 0 14px 0;font-family:Arial,Helvetica,sans-serif;font-size:20px;line-height:26px;font-weight:700;color:#132A50;">${text}</h1>
            <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">
"""
)
_STEP = Template(
    """              <tr>
                <td valign="top" width="36" style="padding:0 0 14px 0;">
                  <div class="bg-num" style="width:28px;height:28px;border-radius:14px;background-color:#164194;color:#FFFFFF;font-family:Arial,Helvetica,sans-serif;font-size:15px;line-height:28px;font-weight:700;text-align:center;">${number}</div>
                </td>
                <td valign="top" style="padding:2px 0 14px 0;">
                  <p class="t-main" style="margin:0;"""
    + _P_STYLE
    + """">${text}</p>${hint}
                </td>
              </tr>
"""
)
_HINT = Template(
    """
                  <p class="t-muted" style="margin:4px 0 0 0;font-family:Arial,Helvetica,sans-serif;font-size:14px;line-height:20px;color:#5B6475;">${text}</p>"""
)
_BUTTON = Template(
    """        <tr>
          <td align="center" style="padding:12px 24px 8px 24px;">
            <a class="bg-btn t-btn" href="${panel_url}" style="display:block;box-sizing:border-box;width:100%;min-height:48px;padding:14px 20px;border-radius:999px;background-color:#164194;color:#FFFFFF;font-family:Arial,Helvetica,sans-serif;font-size:16px;line-height:20px;font-weight:700;text-align:center;text-decoration:none;">${text}</a>
          </td>
        </tr>
"""
)
_HELP = Template(
    """        <tr>
          <td style="padding:8px 24px 0 24px;" align="center">
            <p class="t-muted" style="margin:0;font-family:Arial,Helvetica,sans-serif;font-size:14px;line-height:21px;color:#5B6475;text-align:center;">${text}</p>
          </td>
        </tr>
"""
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
${body}          </td>
        </tr>
${button}${help}        <tr>
          <td style="padding:0 24px 28px 24px;font-size:0;line-height:0;">&nbsp;</td>
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


def _copy(kind: str, lang: str | None, *, shop_name: str, town: str) -> tuple[str, dict[str, str]]:
    """The texts of one email in ``lang``, with the names filled in."""
    L = normalize_invite_lang(lang)
    return L, {
        key: value.replace("{shop_name}", shop_name.strip()).replace("{town}", town.strip())
        for key, value in REVIEW_COPY[L][kind].items()
    }


def review_email_subject(kind: str, lang: str | None = None, *, shop_name: str = "") -> str:
    return _copy(kind, lang, shop_name=shop_name, town="")[1]["subject"]


def render_review_text(
    kind: str,
    *,
    shop_name: str,
    town: str,
    reason: str | None = None,
    panel_url: str | None = None,
    lang: str | None = None,
) -> str:
    _, c = _copy(kind, lang, shop_name=shop_name, town=town)
    lines = [c["subject"], "", c["greeting"], "", c["intro"], ""]
    if "reason_label" in c:
        lines += [c["reason_label"], (reason or "").strip(), ""]
    for key in ("body", "next"):
        if key in c:
            lines += [c[key], ""]
    if "steps_title" in c:
        lines += [
            c["steps_title"],
            f"1. {c['step1']}",
            f"   {c['step1_hint']}",
            f"2. {c['step2']}",
            f"3. {c['step3']}",
            "",
            c["gain"],
            "",
        ]
    if "button" in c and panel_url:
        lines += [f"{c['button']}: {panel_url}", ""]
    if "help" in c:
        lines += [c["help"], ""]
    lines += [c["footer_signature"], ""]
    return "\n".join(lines)


def _html_text(value: str) -> str:
    """Escaped for a text node; the brand never breaks across two lines."""
    return html.escape(value, quote=False).replace("KM0 LAB", "KM0&nbsp;LAB")


def render_review_html(
    kind: str,
    *,
    shop_name: str,
    town: str,
    reason: str | None = None,
    panel_url: str | None = None,
    lang: str | None = None,
) -> str:
    L, raw = _copy(kind, lang, shop_name=shop_name, town=town)
    c = {key: _html_text(value) for key, value in raw.items()}
    body = _PARAGRAPH.substitute(text=c["intro"])
    if "reason_label" in c:
        body += _REASON.substitute(
            label=c["reason_label"],
            # What the administrator wrote, line breaks kept, nothing run.
            reason=html.escape((reason or "").strip(), quote=False).replace("\n", "<br>"),
        )
    for key in ("body", "next"):
        if key in c:
            body += _PARAGRAPH.substitute(text=c[key])
    if "steps_title" in c:
        body += _STEPS_TITLE.substitute(text=c["steps_title"])
        body += "".join(
            _STEP.substitute(
                number=number,
                text=c[key],
                hint=_HINT.substitute(text=c[hint]) if hint else "",
            )
            for number, key, hint in (
                (1, "step1", "step1_hint"),
                (2, "step2", None),
                (3, "step3", None),
            )
        )
        body += "            </table>\n"
        body += _PARAGRAPH.substitute(text=c["gain"])
    button = ""
    if "button" in c and panel_url:
        button = _BUTTON.substitute(
            panel_url=html.escape(panel_url, quote=True), text=c["button"]
        )
    return _HTML.substitute(
        lang=L,
        subject=c["subject"],
        preheader=c["preheader"],
        greeting=c["greeting"],
        body=body,
        button=button,
        help=_HELP.substitute(text=c["help"]) if "help" in c else "",
        footer_signature=c["footer_signature"],
    )
