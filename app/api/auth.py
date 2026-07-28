"""Email OTP auth: request code and verify (signup = first login).

On verify, new users get welcome points via the ledger and a JWT that
embeds role + town/shop scope.
"""

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
from app.services.points import apply_points

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
    is_new = user is None
    if is_new:
        # Check pending merchant invitation by contact_email on a shop.
        from app.models import Shop

        shop = (
            await db.execute(
                select(Shop).where(
                    Shop.contact_email == email,
                    Shop.status == "pending",
                )
            )
        ).scalars().first()
        if shop:
            user = User(
                email=email,
                role="merchant",
                town_id=shop.town_id,
                shop_id=shop.id,
                points=0,
            )
            db.add(user)
            await db.flush()
            shop.status = "active"
        else:
            user = User(email=email, role="resident", points=0)
            db.add(user)
            await db.flush()
            await apply_points(
                db,
                user=user,
                points=settings.welcome_points,
                type="welcome",
                description="Welcome bonus",
            )

    await db.commit()
    await db.refresh(user)

    return AuthOut(
        access_token=create_access_token(
            user.id,
            role=user.role,
            town_id=user.town_id,
            shop_id=user.shop_id,
        ),
        user=UserOut.model_validate(user),
    )
