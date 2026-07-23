"""Auth por OTP de email: pedir código y verificarlo (registro = primer
login). Al verificar, si el usuario no existe se crea con los puntos de
bienvenida y se devuelve un JWT.

Protecciones: rate limit por IP (slowapi) en ambos endpoints y corte por
número de intentos fallidos por código (anti fuerza bruta)."""

import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import get_db
from app.email import send_otp_email
from app.models import OtpCode, User
from app.ratelimit import MAX_OTP_ATTEMPTS, limiter
from app.schemas import AuthOut, MessageOut, RequestOtpIn, UserOut, VerifyOtpIn
from app.security import create_access_token, hash_otp, verify_otp

router = APIRouter(prefix="/auth", tags=["auth"])
settings = get_settings()


def _generate_code() -> str:
    return "".join(secrets.choice("0123456789") for _ in range(settings.otp_length))


@router.post("/request-otp", response_model=MessageOut)
@limiter.limit("5/hour")
async def request_otp(
    request: Request,
    payload: RequestOtpIn,
    db: AsyncSession = Depends(get_db),
):
    """Genera un OTP, lo guarda (hasheado) y lo envía por email. Responde
    igual exista o no el email (no filtra si hay cuenta). Invalida los
    códigos previos no usados del mismo email."""
    email = payload.email.lower()
    await db.execute(
        update(OtpCode)
        .where(OtpCode.email == email, OtpCode.consumed == 0)
        .values(consumed=1)
    )
    code = _generate_code()
    otp = OtpCode(
        email=email,
        code_hash=hash_otp(code),
        expires_at=datetime.now(timezone.utc)
        + timedelta(minutes=settings.otp_ttl_minutes),
    )
    db.add(otp)
    await db.commit()
    await send_otp_email(payload.email, code)
    return MessageOut(message="Si el correu és vàlid, rebràs un codi.")


@router.post("/verify-otp", response_model=AuthOut)
@limiter.limit("10/hour")
async def verify_otp_endpoint(
    request: Request,
    payload: VerifyOtpIn,
    db: AsyncSession = Depends(get_db),
):
    email = payload.email.lower()
    now = datetime.now(timezone.utc)

    result = await db.execute(
        select(OtpCode)
        .where(
            OtpCode.email == email,
            OtpCode.consumed == 0,
            OtpCode.expires_at >= now,
        )
        .order_by(OtpCode.created_at.desc())
    )
    otp = result.scalars().first()

    bad = HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST, detail="Codi invàlid o caducat"
    )
    if not otp:
        raise bad

    if not verify_otp(payload.code, otp.code_hash):
        # Suma intento; si supera el máximo, invalida el código.
        consumed = 1 if otp.attempts + 1 >= MAX_OTP_ATTEMPTS else 0
        await db.execute(
            update(OtpCode)
            .where(OtpCode.id == otp.id)
            .values(attempts=otp.attempts + 1, consumed=consumed)
        )
        await db.commit()
        raise bad

    await db.execute(
        update(OtpCode).where(OtpCode.id == otp.id).values(consumed=1)
    )

    user = (
        await db.execute(select(User).where(User.email == email))
    ).scalars().first()
    if not user:
        user = User(email=email, points=settings.welcome_points)
        db.add(user)

    await db.commit()
    await db.refresh(user)

    return AuthOut(
        access_token=create_access_token(user.id),
        user=UserOut.model_validate(user),
    )
