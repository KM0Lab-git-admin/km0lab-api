"""Envío de emails: el código de acceso y el aviso de alta de un comercio.

Orden de preferencia:
1. Resend API HTTP (`RESEND_API_KEY`) — recomendado en Railway (HTTPS).
2. SMTP (`SMTP_HOST`) — fallback.
3. Sin ninguno → log `[DEV] OTP…` (no se envía correo).

Misma plantilla HTML+texto para app y backoffice (app/catalog/email_otp.py).
"""

import logging

import aiosmtplib
import httpx
from email.message import EmailMessage

from app.catalog.email_otp import (
    normalize_otp_lang,
    otp_subject,
    render_otp_html,
    render_otp_text,
)
from app.catalog.email_shop_invite import (
    normalize_invite_lang,
    render_shop_invite_html,
    render_shop_invite_text,
    shop_invite_subject,
)
from app.catalog.email_shop_review import (
    REVIEW_COPY,
    render_review_html,
    render_review_text,
    review_email_subject,
)
from app.config import get_settings

logger = logging.getLogger("km0lab-api.email")
settings = get_settings()

RESEND_API_URL = "https://api.resend.com/emails"


def _otp_parts(
    code: str,
    *,
    lang: str | None = None,
    email: str | None = None,
) -> tuple[str, str, str]:
    resolved = normalize_otp_lang(lang)
    minutes = settings.otp_ttl_minutes
    subject = otp_subject(code, resolved)
    text = render_otp_text(
        code=code, minutes=minutes, lang=resolved, email=email
    )
    html_body = render_otp_html(
        code=code, minutes=minutes, lang=resolved, email=email
    )
    return subject, text, html_body


async def _send_via_resend(
    to: str,
    code: str,
    *,
    lang: str | None = None,
) -> None:
    subject, text, html_body = _otp_parts(code, lang=lang, email=to)
    payload = {
        "from": settings.smtp_from,
        "to": [to],
        "subject": subject,
        "text": text,
        "html": html_body,
    }
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            RESEND_API_URL,
            headers={
                "Authorization": f"Bearer {settings.resend_api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
        )
    if response.status_code >= 400:
        logger.error(
            "Resend error %s: %s",
            response.status_code,
            response.text,
        )
        response.raise_for_status()
    logger.info("OTP enviado vía Resend a %s (lang=%s)", to, normalize_otp_lang(lang))


async def _send_via_smtp(
    to: str,
    code: str,
    *,
    lang: str | None = None,
) -> None:
    subject, text, html_body = _otp_parts(code, lang=lang, email=to)
    message = EmailMessage()
    message["From"] = settings.smtp_from
    message["To"] = to
    message["Subject"] = subject
    message.set_content(text)
    message.add_alternative(html_body, subtype="html")

    await aiosmtplib.send(
        message,
        hostname=settings.smtp_host,
        port=settings.smtp_port,
        username=settings.smtp_user or None,
        password=settings.smtp_password or None,
        start_tls=True,
    )
    logger.info("OTP enviado vía SMTP a %s (lang=%s)", to, normalize_otp_lang(lang))


async def send_otp_email(to: str, code: str, lang: str | None = None) -> None:
    resolved = normalize_otp_lang(lang)

    if settings.resend_api_key:
        await _send_via_resend(to, code, lang=resolved)
        return

    if settings.smtp_host:
        await _send_via_smtp(to, code, lang=resolved)
        return

    logger.warning(
        "[DEV] OTP para %s: %s (lang=%s, email no configurado)",
        to,
        code,
        resolved,
    )


async def _deliver(to: str, subject: str, text: str, html_body: str) -> bool:
    """Send one email by whatever is configured. False = nothing configured."""
    if settings.resend_api_key:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                RESEND_API_URL,
                headers={
                    "Authorization": f"Bearer {settings.resend_api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "from": settings.smtp_from,
                    "to": [to],
                    "subject": subject,
                    "text": text,
                    "html": html_body,
                },
            )
        if response.status_code >= 400:
            logger.error("Resend error %s: %s", response.status_code, response.text)
            response.raise_for_status()
        return True
    if settings.smtp_host:
        message = EmailMessage()
        message["From"] = settings.smtp_from
        message["To"] = to
        message["Subject"] = subject
        message.set_content(text)
        message.add_alternative(html_body, subtype="html")
        await aiosmtplib.send(
            message,
            hostname=settings.smtp_host,
            port=settings.smtp_port,
            username=settings.smtp_user or None,
            password=settings.smtp_password or None,
            start_tls=True,
        )
        return True
    return False


async def send_shop_invite_email(
    to: str,
    *,
    shop_name: str,
    town: str,
    entity: str | None,
    lang: str | None = None,
) -> bool:
    """Tell a shop it has been registered and how to get into its panel.

    Returns whether an email went out. Without the panel's address
    (``BACKOFFICE_URL``) nothing is sent: a button that leads nowhere is
    worse than no email. The address is not written to the logs.
    """
    panel_url = (get_settings().backoffice_url or "").strip()
    if not panel_url:
        logger.warning("Aviso de alta de comercio no enviado: falta BACKOFFICE_URL")
        return False
    resolved = normalize_invite_lang(lang)
    parts = dict(
        shop_name=shop_name, town=town, entity=entity, panel_url=panel_url, lang=resolved
    )
    sent = await _deliver(
        to,
        shop_invite_subject(resolved),
        render_shop_invite_text(**parts),
        render_shop_invite_html(**parts),
    )
    if sent:
        logger.info("Aviso de alta de comercio enviado (lang=%s)", resolved)
    else:
        logger.warning("[DEV] Aviso de alta de comercio sin enviar (email no configurado)")
    return sent


async def send_shop_review_email(
    kind: str,
    to: str,
    *,
    shop_name: str,
    town: str,
    reason: str | None = None,
    lang: str | None = None,
) -> bool:
    """One of the emails of a shop's request to join (``email_shop_review``).

    Returns whether an email went out. The ones with a button to the panel
    (approved, and the notice to the administrator) are not sent without
    ``BACKOFFICE_URL``, like the invitation.
    """
    resolved = normalize_invite_lang(lang)
    panel_url = (get_settings().backoffice_url or "").strip()
    needs_panel = "button" in REVIEW_COPY[resolved][kind]
    if needs_panel and not panel_url:
        logger.warning("Correo de alta (%s) no enviado: falta BACKOFFICE_URL", kind)
        return False
    parts = dict(
        shop_name=shop_name,
        town=town,
        reason=reason,
        panel_url=panel_url or None,
        lang=resolved,
    )
    sent = await _deliver(
        to,
        review_email_subject(kind, resolved, shop_name=shop_name),
        render_review_text(kind, **parts),
        render_review_html(kind, **parts),
    )
    if sent:
        logger.info("Correo de alta (%s) enviado (lang=%s)", kind, resolved)
    else:
        logger.warning("[DEV] Correo de alta (%s) sin enviar (email no configurado)", kind)
    return sent
