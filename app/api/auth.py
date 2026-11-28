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

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import get_db
from app.deps import get_optional_user
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
from app.ratelimit import (
    MAX_LIVE_OTP_CODES,
    MAX_OTP_ATTEMPTS,
    limiter,
    too_many_response,
)
from app.roles import (
    ROLE_ADMIN,
    ROLE_MERCHANT,
    ROLE_RESIDENT,
    IncompatibleRolesError,
    flags_from_roles,
)
from app.schemas import (
    AuthOut,
    AuthProviderOut,
    AuthProvidersOut,
    MessageOut,
    RequestOtpIn,
    SocialLoginIn,
    VerifyOtpIn,
)
from app.security import create_access_token, hash_otp, verify_otp
from app.services.action_grants import grant_signup_points
from app.services.capacity import (
    PILOT_FULL,
    PILOT_FULL_MESSAGE,
    accept_terms,
    town_is_full,
)
from app.services.invitations import (
    EVENT_REG_STARTED,
    apply_invitee_postal_code,
    convert_business_activation,
    convert_person_signup,
    record_event,
)
from app.services.identities import (
    PROVIDER_EMAIL,
    SOCIAL_PROVIDERS,
    IdentityTaken,
    ensure_identity,
    find_identity,
)
from app.services.social import (
    SocialRefused,
    client_id,
    create_link_token,
    enabled_providers,
    is_enabled,
    read_link_token,
    verify_credential,
)
from app.services.shop_review import user_out
from app.services.slugs import allocate_user_slug
from app.services.towns import (
    assign_user_to_town,
    get_postal_code,
    load_user_with_town,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])
settings = get_settings()


# Per connection (IP) and hour, when the environment sets nothing.
DEFAULT_OTP_REQUESTS_PER_HOUR = 30
DEFAULT_OTP_VERIFIES_PER_HOUR = 60
OTP_EMAIL_LIMIT = "otp_email_limit"


def _per_hour(configured: int | None, default: int) -> str:
    """The limit by connection: the configured one, else the default.

    Loose in local development, where tests and people loop. The fine brake
    is elsewhere and does not depend on the connection: codes alive and
    attempts per code, and codes per hour to the same email.
    """
    if configured and configured > 0:
        return f"{configured}/hour"
    if get_settings().environment.lower().strip() == "development":
        return "600/hour"
    return f"{default}/hour"


def _otp_request_limit() -> str:
    return _per_hour(
        get_settings().otp_requests_per_hour, DEFAULT_OTP_REQUESTS_PER_HOUR
    )


def _otp_verify_limit() -> str:
    return _per_hour(
        get_settings().otp_verifies_per_hour, DEFAULT_OTP_VERIFIES_PER_HOUR
    )


async def _email_wait_seconds(db: AsyncSession, email: str) -> int:
    """Seconds until ``email`` may be sent another code (0 = now).

    At most ``otp_per_email_per_hour`` codes go to one mailbox in an hour,
    whoever asks and from wherever: the limit by connection alone would let
    one person fill somebody else's inbox. Counted on the codes themselves,
    so it survives a restart. A code's ``expires_at`` is when it was asked
    for plus its lifetime; that dates it without trusting the database's
    clock.
    """
    cap = get_settings().otp_per_email_per_hour
    if cap <= 0:
        return 0
    now = datetime.now(timezone.utc)
    lifetime = timedelta(minutes=settings.otp_ttl_minutes)
    asked_within_the_hour = OtpCode.expires_at > now + lifetime - timedelta(hours=1)
    rows = (
        (
            await db.execute(
                select(OtpCode.expires_at)
                .where(OtpCode.email == email, asked_within_the_hour)
                .order_by(OtpCode.expires_at.desc())
                .limit(cap)
            )
        )
        .scalars()
        .all()
    )
    if len(rows) < cap:
        return 0
    # The oldest of the last ``cap`` codes leaves the hour first.
    oldest_asked_at = rows[-1].replace(tzinfo=timezone.utc) - lifetime
    return max(1, int((oldest_asked_at + timedelta(hours=1) - now).total_seconds()))


# Why a code was refused, so the app can say it instead of a blanket
# "wrong code". ``detail`` is ``{"code", "message"}``.
OTP_INVALID = "otp_invalid"
OTP_EXPIRED = "otp_expired"
OTP_TOO_MANY_ATTEMPTS = "otp_too_many_attempts"
OTP_SEND_FAILED = "otp_send_failed"
# Social networks (app/services/social.py).
PROVIDER_DISABLED = "provider_disabled"
PROVIDER_FAILED = "provider_failed"
EMAIL_MISSING = "email_missing"
IDENTIFIER_TAKEN = "identifier_taken"
USE_EMAIL = "use_email"
LINK_EXPIRED = "link_expired"


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


def _pilot_full() -> HTTPException:
    return _otp_error(status.HTTP_409_CONFLICT, PILOT_FULL, PILOT_FULL_MESSAGE)


async def _would_overflow(
    db: AsyncSession, email: str, postal_code: str | None, *, lock: bool = False
) -> bool:
    """A new account for ``email`` in that postal code would exceed the
    municipality's capacity. Never for an existing account, for a shop owner
    the administrator is waiting for, or on the make-believe side."""
    code = (postal_code or "").strip()
    if not code or desired_user_is_fake(email, code):
        return False
    if await db.scalar(select(User.id).where(User.email == email)):
        return False
    postal = await get_postal_code(db, code)
    if postal is None:
        return False
    if await _shop_waiting_for(db, email, is_fake=False) is not None:
        return False
    return await town_is_full(db, postal.town_id, lock=lock)


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
        user=await user_out(db, user),
        points_awarded=points_awarded,
        points_award_message=points_award_message,
    )


async def _came_in_by_email(db: AsyncSession, user: User) -> None:
    """Note the door: the code sent to their email. Never stops a login."""
    try:
        await ensure_identity(
            db, user, provider=PROVIDER_EMAIL, subject=user.email, email=user.email
        )
    except IdentityTaken:
        logger.warning("Email identity of user %s belongs to another account", user.id)


def _taken() -> HTTPException:
    return _otp_error(
        status.HTTP_409_CONFLICT,
        IDENTIFIER_TAKEN,
        "Aquesta xarxa ja entra en un altre compte.",
    )


async def _note_doors(
    db: AsyncSession,
    user: User,
    *,
    door: tuple[str, str],
    also: tuple[str, str] | None = None,
    door_email: str | None = None,
) -> None:
    """Note how the person came in. A network proved a moment ago goes
    first, so it is the origin of an account being born now."""
    if also is not None:
        try:
            await ensure_identity(db, user, provider=also[0], subject=also[1])
        except IdentityTaken:
            raise _taken() from None
    if door[0] == PROVIDER_EMAIL:
        await _came_in_by_email(db, user)
        return
    try:
        await ensure_identity(
            db, user, provider=door[0], subject=door[1], email=door_email
        )
    except IdentityTaken:
        raise _taken() from None


async def _fixed_code_out(db: AsyncSession, user: User) -> AuthOut:
    """Accounts that get in with the fixed code also came in by email."""
    await _came_in_by_email(db, user)
    await db.commit()
    return await _auth_out(db, user)


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

    # A full pilot says so before sending anything: no code is worth
    # waiting for. Whoever already has an account is never stopped here.
    if await _would_overflow(db, email, payload.postal_code):
        raise _pilot_full()

    wait = await _email_wait_seconds(db, email)
    if wait:
        return too_many_response(OTP_EMAIL_LIMIT, wait)

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
            # True for a blip and for a used-up quota alike: no promise of minutes.
            "Ara mateix no podem enviar correus. Prova-ho més tard.",
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
            return await _fixed_code_out(db, user)
        if is_malgrat_qa_email(email):
            if not user or user.is_fake:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Malgrat QA user not seeded — run: python -m scripts.seed",
                )
            return await _fixed_code_out(db, user)
        if is_pilot_admin_email(email):
            # Never created here: only an account already registered as the
            # administrator of a real municipality may use the fixed code.
            if not user or user.is_fake or not user.is_admin:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Pilot admin not registered — run: python -m scripts.add_admin",
                )
            return await _fixed_code_out(db, user)

    # A network proved a moment ago, waiting for an email ("your email is
    # missing"). Checked before the code is spent: a dead token costs nothing.
    also = None
    if payload.link_token:
        also = read_link_token(payload.link_token)
        if also is None:
            raise _otp_error(
                status.HTTP_400_BAD_REQUEST,
                LINK_EXPIRED,
                "Ha passat massa temps. Torna a entrar amb la xarxa.",
            )

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

    return await _sign_in(
        db,
        email=email,
        door=(PROVIDER_EMAIL, email),
        also=also,
        postal_code=payload.postal_code,
        invite_code=(payload.invite_code or "").strip().lower()
        or (otp.invite_code if otp else None),
        terms_version=payload.terms_version,
        qa_postal=qa_postal,
    )


async def _sign_in(
    db: AsyncSession,
    *,
    email: str,
    door: tuple[str, str],
    postal_code: str | None,
    invite_code: str | None,
    terms_version: str | None,
    also: tuple[str, str] | None = None,
    qa_postal=None,
    names: tuple[str | None, str | None] = (None, None),
    door_email: str | None = None,
    account: User | None = None,
) -> AuthOut:
    """Let the owner of ``email`` in, creating the account if there is none.

    The caller has already proved the person is who they say: with the code
    sent to that email, or with a social network that vouches for it.
    ``door`` is (provider, subject) of how they came in now and
    ``door_email`` the email that door handed over. ``also`` is a network
    they proved a moment ago and gave no email ("your email is missing"):
    it is linked here, and it is the origin of an account born now.
    ``account`` is the account, when the caller already found it.
    """
    qa_account = is_qa_email(email)
    user = account
    if user is None:
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
        # The authoritative check, with the municipality's row locked: two
        # people cannot both take the last place. Nothing has been written
        # yet, so the code stays usable if a place opens.
        if await _would_overflow(db, email, postal_code, lock=True):
            raise _pilot_full()
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
            await apply_invitee_postal_code(db, user, postal_code)
        # Settle the partition before granting points, so the welcome bonus
        # and its ledger row land on the same side as the user.
        sync_user_fake_partition(user)
        # The app does not let anyone get here without ticking the box.
        accept_terms(user, terms_version)
        if is_new and not user.first_name and not user.last_name:
            user.first_name, user.last_name = (
                (names[0] or "").strip() or None,
                (names[1] or "").strip() or None,
            )
        await _note_doors(db, user, door=door, also=also, door_email=door_email)

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


# ── Social networks ───────────────────────────────────────────────────


@router.get("/providers", response_model=AuthProvidersOut)
async def auth_providers(
    x_app_platform: str | None = Header(default=None, alias="X-App-Platform"),
):
    """The networks to offer next to the email, for the platform that asks.

    The app shows only these buttons, so a network is switched on from the
    environment without publishing the app. Empty = email only.
    """
    return AuthProvidersOut(
        providers=[
            AuthProviderOut(provider=p, client_id=client_id(p))
            for p in enabled_providers(x_app_platform)
        ]
    )


def _use_email() -> HTTPException:
    return _otp_error(
        status.HTTP_403_FORBIDDEN, USE_EMAIL, "Aquest compte entra amb el correu."
    )


@router.post("/social/{provider}", response_model=AuthOut)
@limiter.limit(_otp_verify_limit)
async def social_login(
    request: Request,
    provider: str,
    payload: SocialLoginIn,
    current: User | None = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
):
    """Get in with a social network, or link one to the account in session.

    The network vouches for who the person is (``app/services/social.py``).
    From there it is the same way in as the code by email:

    - the network is already linked to an account: that account;
    - if not, and the network gives a **verified** email: the account with
      that email, or a new one;
    - with no email we can trust: 409 ``email_missing`` and a short-lived
      ``link_token``; the person types an email, confirms it with the code
      and ``verify-otp`` links the network (send it as ``link_token``).

    With a session, it links the network to that account instead (409
    ``identifier_taken`` if it already opens another one).
    """
    provider = provider.strip().lower()
    if provider not in SOCIAL_PROVIDERS or not is_enabled(provider):
        raise _otp_error(
            status.HTTP_404_NOT_FOUND, PROVIDER_DISABLED, "Aquesta xarxa no està activa."
        )
    try:
        profile = await verify_credential(provider, payload.credential)
    except SocialRefused:
        raise _otp_error(
            status.HTTP_401_UNAUTHORIZED,
            PROVIDER_FAILED,
            "No hem pogut entrar amb aquesta xarxa.",
        ) from None
    except Exception:
        logger.exception("Social sign-in with %s failed", provider)
        raise _otp_error(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            PROVIDER_FAILED,
            "No hem pogut entrar amb aquesta xarxa.",
        ) from None
    door = (provider, profile.subject.strip())

    def _email_only(email: str, user: User | None) -> bool:
        # Test and fixed-code accounts, and administrators, get in by email.
        return (
            is_fixed_otp_email(email)
            or is_qa_email(email)
            or (user is not None and user.has_role(ROLE_ADMIN))
        )

    # With a session: link this network to that account.
    if current is not None:
        if _email_only(current.email, current):
            raise _use_email()
        await _note_doors(db, current, door=door, door_email=profile.email)
        await db.commit()
        return await _auth_out(db, current)

    known = await find_identity(db, *door)
    if known is not None:
        owner = await load_user_with_town(db, known.user_id)
        email = owner.email.lower()
    elif profile.email and profile.email_verified:
        email = profile.email.strip().lower()
        owner = (
            await db.execute(select(User).where(User.email == email))
        ).scalars().first()
    else:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": EMAIL_MISSING,
                "message": "Falta el teu correu.",
                "link_token": create_link_token(*door),
            },
        )
    if _email_only(email, owner):
        raise _use_email()

    return await _sign_in(
        db,
        email=email,
        door=door,
        postal_code=payload.postal_code,
        invite_code=(payload.invite_code or "").strip().lower() or None,
        terms_version=payload.terms_version,
        names=(
            payload.first_name or profile.first_name,
            payload.last_name or profile.last_name,
        ),
        door_email=profile.email,
        account=owner,
    )
