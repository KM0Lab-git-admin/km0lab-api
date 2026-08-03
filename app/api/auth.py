"""Email OTP auth: request code and verify (signup = first login).

Identity is the email. Users may hold multiple roles (resident+merchant
or resident+admin; never admin+merchant). JWT embeds the full roles list
plus town/shop scope.

Demo accounts (dev/staging): resident@ / merchant@ / admin@km0lab.com
authenticate with fixed code 123456 and only see is_fake content.
"""

import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import get_db
from app.demo import (
    DEMO_CODE,
    DEMO_ROLES,
    demo_enabled,
    is_demo_email,
)
from app.catalog.email_otp import normalize_otp_lang
from app.email import send_otp_email
from app.models import OtpCode, User
from app.ratelimit import MAX_OTP_ATTEMPTS, limiter
from app.roles import (
    ROLE_ADMIN,
    ROLE_MERCHANT,
    ROLE_RESIDENT,
    IncompatibleRolesError,
    flags_from_roles,
)
from app.schemas import AuthOut, MessageOut, RequestOtpIn, UserOut, VerifyOtpIn
from app.security import create_access_token, hash_otp, verify_otp
from app.services.action_grants import grant_signup_points
from app.services.slugs import allocate_user_slug
from app.services.towns import assign_user_to_town, load_user_with_town

router = APIRouter(prefix="/auth", tags=["auth"])
settings = get_settings()


def _otp_request_limit() -> str:
    """Demo/local: generous; production: tight."""
    env = get_settings().environment.lower().strip()
    return "60/hour" if env in {"development", "staging"} else "5/hour"


def _otp_verify_limit() -> str:
    env = get_settings().environment.lower().strip()
    return "60/hour" if env in {"development", "staging"} else "10/hour"


def _generate_code() -> str:
    return "".join(secrets.choice("0123456789") for _ in range(settings.otp_length))


async def _auth_out(
    db: AsyncSession,
    user: User,
    *,
    points_awarded: int | None = None,
    points_award_message: str | None = None,
) -> AuthOut:
    user = await load_user_with_town(db, user.id)
    return AuthOut(
        access_token=create_access_token(
            user.id,
            roles=user.roles,
            town_id=user.town_id,
            shop_id=user.shop_id,
        ),
        user=UserOut.model_validate(user),
        points_awarded=points_awarded,
        points_award_message=points_award_message,
    )


@router.post("/request-otp", response_model=MessageOut)
@limiter.limit(_otp_request_limit)
async def request_otp(
    request: Request,
    payload: RequestOtpIn,
    db: AsyncSession = Depends(get_db),
):
    email = payload.email.lower()
    if is_demo_email(email):
        if not demo_enabled():
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Demo login disabled in this environment",
            )
        # No email sent — client proceeds with fixed code 123456.
        return MessageOut(message="Si el correu és vàlid, rebràs un codi.")

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

    # Prefer explicit lang from app/BO; else stored user.lang; else Spanish.
    lang = payload.lang
    if not lang:
        stored = await db.scalar(select(User.lang).where(User.email == email))
        lang = stored
    await send_otp_email(payload.email, code, lang=normalize_otp_lang(lang))
    return MessageOut(message="Si el correu és vàlid, rebràs un codi.")


@router.post("/verify-otp", response_model=AuthOut)
@limiter.limit(_otp_verify_limit)
async def verify_otp_endpoint(
    request: Request,
    payload: VerifyOtpIn,
    db: AsyncSession = Depends(get_db),
):
    email = payload.email.lower()

    if is_demo_email(email):
        if not demo_enabled():
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Demo login disabled in this environment",
            )
        if payload.code != DEMO_CODE:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Codi invàlid o caducat",
            )
        user = (
            await db.execute(select(User).where(User.email == email))
        ).scalars().first()
        if not user or not user.is_fake:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Demo user not seeded — run: python -m scripts.seed_demo",
            )
        return await _auth_out(db, user)

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
    grant_welcome = False

    from app.models import Shop

    shop = (
        await db.execute(
            select(Shop).where(
                Shop.contact_email == email,
                Shop.status == "pending",
                Shop.is_fake.is_(False),
            )
        )
    ).scalars().first()

    if shop:
        if user and user.has_role(ROLE_ADMIN):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Admin cannot also be merchant",
            )
        try:
            merchant_flags = flags_from_roles([ROLE_RESIDENT, ROLE_MERCHANT])
        except IncompatibleRolesError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
            ) from exc

        if is_new:
            user = User(
                email=email,
                slug=await allocate_user_slug(db, email=email),
                shop_id=shop.id,
                points=0,
                is_fake=False,
                **merchant_flags,
            )
            db.add(user)
            await db.flush()
            await assign_user_to_town(db, user, shop.town_id)
            grant_welcome = True
        else:
            if not user.has_role(ROLE_MERCHANT):
                user.set_roles(
                    list({*user.roles, ROLE_RESIDENT, ROLE_MERCHANT})
                )
            user.shop_id = shop.id
            await assign_user_to_town(db, user, shop.town_id)
        shop.status = "active"
    elif is_new:
        user = User(
            email=email,
            slug=await allocate_user_slug(db, email=email),
            points=0,
            is_fake=False,
            **flags_from_roles([ROLE_RESIDENT]),
        )
        db.add(user)
        await db.flush()
        grant_welcome = True

    points_awarded: int | None = None
    points_award_message: str | None = None
    if grant_welcome and user is not None:
        grant = await grant_signup_points(db, user=user)
        if grant.points > 0:
            points_awarded = grant.points
            points_award_message = grant.message

    await db.commit()
    return await _auth_out(
        db,
        user,
        points_awarded=points_awarded,
        points_award_message=points_award_message,
    )
