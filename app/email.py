"""Envío de emails OTP.

Orden de preferencia:
1. Resend API HTTP (`RESEND_API_KEY`) — recomendado en Railway (HTTPS).
2. SMTP (`SMTP_HOST`) — fallback.
3. Sin ninguno → log `[DEV] OTP…` (no se envía correo).
"""

import logging

import aiosmtplib
import httpx
from email.message import EmailMessage

from app.config import get_settings

logger = logging.getLogger("km0lab-api.email")
settings = get_settings()

RESEND_API_URL = "https://api.resend.com/emails"


def _otp_subject() -> str:
    return "El teu codi d'accés a KM0 LAB"


def _otp_body(code: str) -> str:
    return (
        f"Hola!\n\nEl teu codi d'accés és: {code}\n"
        f"Caduca en {settings.otp_ttl_minutes} minuts.\n\n"
        "Si no has demanat aquest codi, ignora aquest correu.\n\n— KM0 LAB"
    )


async def _send_via_resend(to: str, code: str) -> None:
    payload = {
        "from": settings.smtp_from,
        "to": [to],
        "subject": _otp_subject(),
        "text": _otp_body(code),
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
    logger.info("OTP enviado vía Resend a %s", to)


async def _send_via_smtp(to: str, code: str) -> None:
    message = EmailMessage()
    message["From"] = settings.smtp_from
    message["To"] = to
    message["Subject"] = _otp_subject()
    message.set_content(_otp_body(code))

    await aiosmtplib.send(
        message,
        hostname=settings.smtp_host,
        port=settings.smtp_port,
        username=settings.smtp_user or None,
        password=settings.smtp_password or None,
        start_tls=True,
    )
    logger.info("OTP enviado vía SMTP a %s", to)


async def send_otp_email(to: str, code: str) -> None:
    if settings.resend_api_key:
        await _send_via_resend(to, code)
        return

    if settings.smtp_host:
        await _send_via_smtp(to, code)
        return

    logger.warning("[DEV] OTP para %s: %s (email no configurado)", to, code)
