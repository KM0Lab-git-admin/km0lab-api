"""Envío de emails OTP.

Orden de preferencia:
1. Resend API HTTP (`RESEND_API_KEY`) — recomendado en Railway (HTTPS).
2. SMTP (`SMTP_HOST`) — fallback.
3. Sin ninguno → log `[DEV] OTP…` (no se envía correo).

Misma plantilla HTML+texto para app y backoffice (Lovable EmailOtpTemplate).
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
    subject = otp_subject(resolved)
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
