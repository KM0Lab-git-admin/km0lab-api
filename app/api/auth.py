"""Email OTP auth: request code and verify (signup = first login).

Identity is the email. Users may hold multiple roles (resident+merchant
or resident+admin; never admin+merchant). JWT embeds the full roles list
plus town/shop scope.

Fixed OTP 123456 (dev/staging only):
- Demo KM0 (is_fake): resident@ / merchant@ / admin@km0lab.com
- Malgrat real: admin-malgrat@ / merchant1-malgrat@ / merchant2-malgrat@km0lab.com
- QA territory (is_fake, CP 9999x): qa+<anything>@km0lab.com. Unlike the
  two above, these go through the normal signup flow, so tests can create
  brand-new residents without a mailbox. See ``app/qa.py``.
"""

import secrets
import logging
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import get_db
from app.demo import (
    DEMO_CODE,
    demo_enabled,
    desired_user_is_fake,
    is_demo_email,
    is_fixed_otp_email,
    is_malgrat_qa_email,
    is_pilot_admin_email,
    sync_user_fake_partition,
)
from app.catalog.email_otp import normalize_otp_lang
from app.email import send_otp_email
from app.models import OtpCode, Shop, User
from app.qa import QA_POSTAL_CODE, is_qa_email, is_qa_postal_code
from app.ratelimit import MAX_LIVE_OTP_CODES, MAX_OTP_ATTEMPTS, limiter
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
from app.services.invitations import (
    EVENT_REG_STARTED,
    apply_invitee_postal_code,
    convert_business_activation,
    convert_person_signup,
    record_event,
)
from app.services.slugs import allocate_user_slug
from app.services.towns import (
    assign_user_to_town,
    get_postal_code,
    load_user_with_town,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])
settings = get_settings()


_OTP_REQUEST_LIMITS = {"development": "600/hour", "staging": "60/hour"}
_OTP_VERIFY_LIMITS = {"development": "600/hour", "staging": "60/hour"}


def _otp_request_limit() -> str:
    """Local: holgado (pruebas en bucle); UAT: generoso; producción: estricto."""
    env = get_settings().environment.lower().strip()
    return _OTP_REQUEST_LIMITS.get(env, "5/hour")


def _otp_verify_limit() -> str:
    env = get_settings().environment.lower().strip()
    return _OTP_VERIFY_LIMITS.get(env, "10/hour")


# Why a code was refused, so the app can say it instead of a blanket
# "wrong code". ``detail`` is ``{"code", "message"}``.
OTP_INVALID = "otp_invalid"
OTP_EXPIRED = "otp_expired"
OTP_TOO_MANY_ATTEMPTS = "otp_too_many_attempts"
OTP_SEND_FAILED = "otp_send_failed"


def _otp_error(status_code: int, code: str, message: str) -> HTTPException:
    return HTTPException(
        status_code=status_code, detail={"code": code, "message": message}
    )


async def _no_live_code_error(db: AsyncSession, email: str) -> HTTPException:
    """No usable code for this email: say whether it expired or burned out."""
    last = (
        await db.execute(
            select(OtpCode)
            .where(OtpCode.email == email)
            .order_by(OtpCode.created_at.desc())
            .limit(1)
        )
    ).scalars().first()
    if last is None:
        return _otp_error(
            status.HTTP_400_BAD_REQUEST, OTP_INVALID, "Codi incorrecte."
        )
    if last.attempts >= MAX_OTP_ATTEMPTS:
        return _otp_error(
            status.HTTP_400_BAD_REQUEST,
            OTP_TOO_MANY_ATTEMPTS,
            "Massa intents. Demana un codi nou.",
        )
    return _otp_error(
        status.HTTP_400_BAD_REQUEST,
        OTP_EXPIRED,
        "Aquest codi ha caducat. Demana'n un de nou.",
    )


async def _shop_waiting_for(
    db: AsyncSession, email: str, *, is_fake: bool
) -> Shop | None:
    """The shop this email was given as contact for and nobody runs yet.

    Registering a shop with someone's email is the invitation: the first
    time that person logs in, the shop is theirs. It does not matter whether
    the administrator switched the shop on in the meantime — only a shop
    that is switched off, or that already has its owner, is left alone.
    """
    claimed = select(User.id).where(User.shop_id == Shop.id).exists()
    return (
        (
            await db.execute(
                select(Shop)
                .where(
                    Shop.contact_email == email,
                    Shop.status.in_(("pending", "active")),
                    Shop.is_fake.is_(is_fake),
                    ~claimed,
                )
                # The one still waiting first, then the oldest.
                .order_by(Shop.status.desc(), Shop.created_at, Shop.id)
            )
        )
        .scalars()
        .first()
    )


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
    if is_fixed_otp_email(email):
        if not demo_enabled():
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Fixed OTP login disabled in this environment",
            )
        # No email sent — client proceeds with fixed code 123456.
        return MessageOut(message="Si el correu és vàlid, rebràs un codi.")

    # Earlier codes stay valid until they expire: whoever asks twice and
    # opens the first email must still get in. Wrong guesses count against
    # every live code at once (see verify), and only MAX_LIVE_OTP_CODES stay
    # live (the oldest is retired below, once the new one has been sent).
    code = _generate_code()
    otp = OtpCode(
        email=email,
        code_hash=hash_otp(code),
        expires_at=datetime.now(timezone.utc)
        + timedelta(minutes=settings.otp_ttl_minutes),
        invite_code=(payload.invite_code or "").strip().lower() or None,
    )
    db.add(otp)
    await db.flush()
    if otp.invite_code:
        await record_event(
            db, event_type=EVENT_REG_STARTED, code=otp.invite_code
        )
    await db.commit()

    # Prefer explicit lang from app/BO; else stored user.lang; else Spanish.
    lang = payload.lang
    if not lang:
        stored = await db.scalar(select(User.lang).where(User.email == email))
        lang = stored
    try:
        await send_otp_email(payload.email, code, lang=normalize_otp_lang(lang))
    except Exception:
        # The code never reached anyone: retire it and say so. Codes sent
        # before are untouched, so the person is not left without a valid one.
        logger.exception("OTP email could not be sent to %s", email)
        await db.execute(
            update(OtpCode).where(OtpCode.id == otp.id).values(consumed=1)
        )
        await db.commit()
        raise _otp_error(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            OTP_SEND_FAILED,
            "No hem pogut enviar el correu. Torna-ho a provar d'aquí a uns minuts.",
        ) from None

    # The new code is out: keep it and the most recent earlier ones, retire
    # the rest. Done after sending so a failed email retires nothing.
    earlier = (
        (
            await db.execute(
                select(OtpCode.id)
                .where(
                    OtpCode.email == email,
                    OtpCode.consumed == 0,
                    OtpCode.expires_at >= datetime.now(timezone.utc),
                    OtpCode.id != otp.id,
                )
                .order_by(OtpCode.created_at.desc())
            )
        )
        .scalars()
        .all()
    )
    surplus = earlier[MAX_LIVE_OTP_CODES - 1 :]
    if surplus:
        await db.execute(
            update(OtpCode).where(OtpCode.id.in_(surplus)).values(consumed=1)
        )
        await db.commit()
    return MessageOut(message="Si el correu és vàlid, rebràs un codi.")


@router.post("/verify-otp", response_model=AuthOut)
@limiter.limit(_otp_verify_limit)
async def verify_otp_endpoint(
    request: Request,
    payload: VerifyOtpIn,
    db: AsyncSession = Depends(get_db),
):
    email = payload.email.lower()

    if is_fixed_otp_email(email):
        if not demo_enabled():
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Fixed OTP login disabled in this environment",
            )
        if payload.code != DEMO_CODE:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Codi invàlid o caducat",
            )
        user = (
            await db.execute(select(User).where(User.email == email))
        ).scalars().first()
        if is_demo_email(email):
            if not user or not user.is_fake:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Demo user not seeded — run: python -m scripts.seed_demo",
                )
            return await _auth_out(db, user)
        if is_malgrat_qa_email(email):
            if not user or user.is_fake:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Malgrat QA user not seeded — run: python -m scripts.seed",
                )
            return await _auth_out(db, user)
        if is_pilot_admin_email(email):
            # Never created here: only an account already registered as the
            # administrator of a real municipality may use the fixed code.
            if not user or user.is_fake or not user.is_admin:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Pilot admin not registered — run: python -m scripts.add_admin",
                )
            return await _auth_out(db, user)

    # QA territory accounts: the fixed code was checked above and no OTP row
    # exists; from here on they follow the same path as any other signup.
    qa_account = is_qa_email(email)
    qa_postal = None
    if qa_account:
        wanted = (payload.postal_code or "").strip()
        qa_postal = await get_postal_code(
            db, wanted if is_qa_postal_code(wanted) else QA_POSTAL_CODE
        )
        if qa_postal is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="QA territory not seeded — run: python -m scripts.seed_qa",
            )

    otp: OtpCode | None = None
    if not qa_account:
        now = datetime.now(timezone.utc)

        live = (
            (
                await db.execute(
                    select(OtpCode)
                    .where(
                        OtpCode.email == email,
                        OtpCode.consumed == 0,
                        OtpCode.expires_at >= now,
                    )
                    .order_by(OtpCode.created_at.desc())
                )
            )
            .scalars()
            .all()
        )
        if not live:
            raise await _no_live_code_error(db, email)

        otp = next(
            (c for c in live if verify_otp(payload.code, c.code_hash)), None
        )
        if otp is None:
            # A wrong guess counts against every live code, so asking for
            # more codes does not buy more guesses.
            exhausted = True
            for candidate in live:
                attempts = candidate.attempts + 1
                dead = attempts >= MAX_OTP_ATTEMPTS
                exhausted = exhausted and dead
                await db.execute(
                    update(OtpCode)
                    .where(OtpCode.id == candidate.id)
                    .values(attempts=attempts, consumed=1 if dead else 0)
                )
            await db.commit()
            if exhausted:
                raise _otp_error(
                    status.HTTP_400_BAD_REQUEST,
                    OTP_TOO_MANY_ATTEMPTS,
                    "Massa intents. Demana un codi nou.",
                )
            raise _otp_error(
                status.HTTP_400_BAD_REQUEST, OTP_INVALID, "Codi incorrecte."
            )

        # One code, one login: the others die with it.
        await db.execute(
            update(OtpCode)
            .where(OtpCode.id.in_([c.id for c in live]))
            .values(consumed=1)
        )

    user = (
        await db.execute(select(User).where(User.email == email))
    ).scalars().first()
    is_new = user is None
    grant_welcome = False

    # An administrator stays an administrator, and whoever already runs a
    # shop keeps it: neither is handed another one for logging in.
    shop = None
    if user is None or not (user.has_role(ROLE_ADMIN) or user.shop_id):
        # A QA account only ever takes a QA (fake) shop.
        shop = await _shop_waiting_for(db, email, is_fake=qa_account)

    if shop:
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
                is_fake=desired_user_is_fake(email, None),
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
        await convert_business_activation(db, user=user, shop=shop)
    elif is_new:
        user = User(
            email=email,
            slug=await allocate_user_slug(db, email=email),
            points=0,
            is_fake=desired_user_is_fake(email, None),
            **flags_from_roles([ROLE_RESIDENT]),
        )
        db.add(user)
        await db.flush()
        grant_welcome = True

    if user is not None:
        if qa_postal is not None:
            # QA accounts never leave the QA territory.
            if not is_qa_postal_code(user.postal_code):
                user.postal_code = qa_postal.postal_code
                user.postal_ref = qa_postal
        else:
            await apply_invitee_postal_code(db, user, payload.postal_code)
        # Settle the partition before granting points, so the welcome bonus
        # and its ledger row land on the same side as the user.
        sync_user_fake_partition(user)

    invite_code = (payload.invite_code or "").strip().lower() or (
        otp.invite_code if otp else None
    )

    points_awarded: int | None = None
    points_award_message: str | None = None
    if grant_welcome and user is not None:
        grant = await grant_signup_points(db, user=user)
        if grant.points > 0:
            points_awarded = grant.points
            points_award_message = grant.message
        if is_new and shop is None:
            await convert_person_signup(db, user=user, invite_code=invite_code)

    await db.commit()
    return await _auth_out(
        db,
        user,
        points_awarded=points_awarded,
        points_award_message=points_award_message,
    )
