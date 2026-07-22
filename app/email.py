"""Envío de emails. Pluggable: en development sin SMTP configurado, el
código se registra en el log (no se envía correo real)."""

import logging

import aiosmtplib
from email.message import EmailMessage

from app.config import get_settings

logger = logging.getLogger("km0lab-api.email")
settings = get_settings()


async def send_otp_email(to: str, code: str) -> None:
    subject = "El teu codi d'accés a KM0 LAB"
    body = (
        f"Hola!\n\nEl teu codi d'accés és: {code}\n"
        f"Caduca en {settings.otp_ttl_minutes} minuts.\n\n"
        "Si no has demanat aquest codi, ignora aquest correu.\n\n— KM0 LAB"
    )

    if not settings.smtp_host:
        # Dev sin SMTP: no enviamos, solo log (nunca en producción).
        logger.warning("[DEV] OTP para %s: %s (SMTP no configurado)", to, code)
        return

    message = EmailMessage()
    message["From"] = settings.smtp_from
    message["To"] = to
    message["Subject"] = subject
    message.set_content(body)

    await aiosmtplib.send(
        message,
        hostname=settings.smtp_host,
        port=settings.smtp_port,
        username=settings.smtp_user or None,
        password=settings.smtp_password or None,
        start_tls=True,
    )
