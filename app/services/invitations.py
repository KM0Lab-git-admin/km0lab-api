"""Invitation links, last-click binding, conversions and inviter rewards."""

from __future__ import annotations

import secrets
import string
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models import (
    InvitationConversion,
    InvitationEvent,
    InvitationLink,
    Shop,
    Town,
    User,
)
from app.services.action_grants import find_active_action
from app.services.points import apply_points
from app.services.towns import get_postal_code

KIND_PERSON = "person"
KIND_BUSINESS = "business"
VALID_KINDS = frozenset({KIND_PERSON, KIND_BUSINESS})

STATUS_ACTIVE = "active"
STATUS_PENDING = "pending_reward"
STATUS_GRANTED = "granted"
STATUS_FAILED = "failed"

TX_INVITE_PERSON = "invite_person"
TX_INVITE_BUSINESS = "invite_business"
ACTION_INVITE_PERSON = "invite_person"
ACTION_INVITE_BUSINESS = "invite_business"

EVENT_SHARE = "share_initiated"
EVENT_RESOLVED = "link_resolved"
EVENT_REG_STARTED = "registration_started"
EVENT_INSTALL = "install_referrer_recovered"
VALID_EVENTS = frozenset(
    {EVENT_SHARE, EVENT_RESOLVED, EVENT_REG_STARTED, EVENT_INSTALL}
)

_CODE_ALPHABET = string.ascii_lowercase + string.digits
_CODE_LEN = 10

BOT_UA_MARKERS = (
    "whatsapp",
    "facebookexternalhit",
    "facebot",
    "twitterbot",
    "slackbot",
    "telegrambot",
    "linkedinbot",
    "discordbot",
)


def is_preview_bot(user_agent: str | None) -> bool:
    ua = (user_agent or "").lower()
    return any(marker in ua for marker in BOT_UA_MARKERS)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _normalize_code(code: str | None) -> str | None:
    if not code:
        return None
    cleaned = code.strip().lower()
    return cleaned or None


def _generate_code() -> str:
    return "".join(secrets.choice(_CODE_ALPHABET) for _ in range(_CODE_LEN))


async def get_link_by_code(
    db: AsyncSession, code: str | None
) -> InvitationLink | None:
    public = _normalize_code(code)
    if not public:
        return None
    return (
        await db.execute(
            select(InvitationLink).where(
                InvitationLink.public_code == public,
                InvitationLink.status == STATUS_ACTIVE,
            )
        )
    ).scalars().first()


async def get_or_create_link(
    db: AsyncSession, *, user: User, kind: str
) -> InvitationLink:
    if kind not in VALID_KINDS:
        raise ValueError("invalid kind")
    if not user.town_id:
        raise ValueError("user has no town")

    existing = (
        await db.execute(
            select(InvitationLink).where(
                InvitationLink.inviter_user_id == user.id,
                InvitationLink.kind == kind,
            )
        )
    ).scalars().first()
    if existing:
        return existing

    for _ in range(8):
        link = InvitationLink(
            public_code=_generate_code(),
            inviter_user_id=user.id,
            kind=kind,
            town_id=user.town_id,
            status=STATUS_ACTIVE,
        )
        try:
            async with db.begin_nested():
                db.add(link)
                await db.flush()
            return link
        except IntegrityError:
            existing = (
                await db.execute(
                    select(InvitationLink).where(
                        InvitationLink.inviter_user_id == user.id,
                        InvitationLink.kind == kind,
                    )
                )
            ).scalars().first()
            if existing:
                return existing
    raise RuntimeError("could not allocate invitation code")


async def record_event(
    db: AsyncSession,
    *,
    event_type: str,
    code: str | None = None,
    channel: str | None = None,
    actor_user_id: str | None = None,
) -> InvitationEvent | None:
    if event_type not in VALID_EVENTS:
        raise ValueError("invalid event")
    link = await get_link_by_code(db, code) if code else None
    event = InvitationEvent(
        link_id=link.id if link else None,
        event_type=event_type,
        channel=channel,
        actor_user_id=actor_user_id,
    )
    db.add(event)
    await db.flush()
    return event


async def resolve_link(
    db: AsyncSession,
    *,
    code: str,
    record: bool = True,
    user_agent: str | None = None,
) -> tuple[InvitationLink, Town] | None:
    link = await get_link_by_code(db, code)
    if link is None:
        return None
    town = await db.get(Town, link.town_id)
    if town is None:
        return None
    if record and not is_preview_bot(user_agent):
        await record_event(db, event_type=EVENT_RESOLVED, code=link.public_code)
    return link, town


async def snapshot_reward_points(
    db: AsyncSession,
    *,
    kind: str,
    town_id: str,
    user: User,
) -> int:
    action_type = (
        ACTION_INVITE_PERSON if kind == KIND_PERSON else ACTION_INVITE_BUSINESS
    )
    action = await find_active_action(
        db, action_type=action_type, user=user, town_id=town_id
    )
    if action is not None and action.points > 0:
        return action.points
    settings = get_settings()
    if kind == KIND_BUSINESS:
        return settings.invite_business_points
    return settings.invite_person_points


async def apply_invitee_postal_code(
    db: AsyncSession, user: User, postal_code: str | None
) -> None:
    if not postal_code or user.postal_code:
        return
    postal = await get_postal_code(db, postal_code.strip())
    if postal is None:
        return
    user.postal_code = postal.postal_code
    user.postal_ref = postal


async def grant_conversion_reward(
    db: AsyncSession, conversion: InvitationConversion
) -> InvitationConversion:
    if conversion.status == STATUS_GRANTED and conversion.points_tx_id:
        return conversion
    if conversion.reward_points <= 0:
        conversion.status = STATUS_GRANTED
        conversion.granted_at = conversion.granted_at or _now()
        return conversion

    link = await db.get(InvitationLink, conversion.link_id)
    if link is None:
        conversion.status = STATUS_FAILED
        return conversion
    inviter = await db.get(User, link.inviter_user_id)
    if inviter is None:
        conversion.status = STATUS_FAILED
        return conversion

    tx_type = (
        TX_INVITE_PERSON if conversion.kind == KIND_PERSON else TX_INVITE_BUSINESS
    )
    try:
        async with db.begin_nested():
            tx = await apply_points(
                db,
                user=inviter,
                points=conversion.reward_points,
                type=tx_type,
                town_id=conversion.town_id,
                ref_id=conversion.id,
                description=(
                    "Invitació de veí"
                    if conversion.kind == KIND_PERSON
                    else "Invitació de comerç"
                ),
            )
    except IntegrityError:
        conversion.status = STATUS_GRANTED
        conversion.granted_at = conversion.granted_at or _now()
        return conversion
    except Exception:
        conversion.status = STATUS_FAILED
        return conversion

    conversion.points_tx_id = tx.id
    conversion.status = STATUS_GRANTED
    conversion.granted_at = _now()
    return conversion


async def _existing_person_conversion(
    db: AsyncSession, invitee_user_id: str
) -> InvitationConversion | None:
    return (
        await db.execute(
            select(InvitationConversion).where(
                InvitationConversion.kind == KIND_PERSON,
                InvitationConversion.invitee_user_id == invitee_user_id,
            )
        )
    ).scalars().first()


async def convert_person_signup(
    db: AsyncSession,
    *,
    user: User,
    invite_code: str | None,
) -> InvitationConversion | None:
    link = await get_link_by_code(db, invite_code)
    if link is None or link.kind != KIND_PERSON:
        return None
    if link.inviter_user_id == user.id:
        return None
    if not user.town_id or user.town_id != link.town_id:
        return None
    if await _existing_person_conversion(db, user.id):
        return None

    inviter = await db.get(User, link.inviter_user_id)
    if inviter is None:
        return None
    points = await snapshot_reward_points(
        db, kind=KIND_PERSON, town_id=link.town_id, user=inviter
    )
    conversion = InvitationConversion(
        link_id=link.id,
        kind=KIND_PERSON,
        invitee_user_id=user.id,
        town_id=link.town_id,
        status=STATUS_PENDING,
        reward_points=points,
        display_name=user.name or user.slug or user.email,
        completed_at=_now(),
    )
    try:
        async with db.begin_nested():
            db.add(conversion)
            await db.flush()
    except IntegrityError:
        return await _existing_person_conversion(db, user.id)

    return await grant_conversion_reward(db, conversion)


async def _conversion_for_shop(
    db: AsyncSession, shop_id: str
) -> InvitationConversion | None:
    return (
        await db.execute(
            select(InvitationConversion).where(
                InvitationConversion.shop_id == shop_id
            )
        )
    ).scalars().first()


async def attach_business_conversion(
    db: AsyncSession,
    *,
    shop: Shop,
    invite_code: str | None,
) -> InvitationConversion | None:
    """Create a pending business conversion at public signup (no reward yet)."""
    if await _conversion_for_shop(db, shop.id):
        return None
    link = await get_link_by_code(db, invite_code)
    if link is None or link.kind != KIND_BUSINESS:
        return None
    if shop.town_id != link.town_id:
        return None
    inviter = await db.get(User, link.inviter_user_id)
    if inviter is None:
        return None
    points = await snapshot_reward_points(
        db, kind=KIND_BUSINESS, town_id=link.town_id, user=inviter
    )
    conversion = InvitationConversion(
        link_id=link.id,
        kind=KIND_BUSINESS,
        shop_id=shop.id,
        town_id=link.town_id,
        status=STATUS_PENDING,
        reward_points=points,
        display_name=shop.name,
    )
    try:
        async with db.begin_nested():
            db.add(conversion)
            await db.flush()
    except IntegrityError:
        return await _conversion_for_shop(db, shop.id)
    return conversion


async def convert_business_activation(
    db: AsyncSession,
    *,
    user: User,
    shop: Shop,
) -> InvitationConversion | None:
    conversion = await _conversion_for_shop(db, shop.id)
    if conversion is None:
        return None
    link = await db.get(InvitationLink, conversion.link_id)
    if link and link.inviter_user_id == user.id:
        return None
    if user.town_id and conversion.town_id != user.town_id:
        return None
    conversion.invitee_user_id = user.id
    conversion.display_name = shop.name
    conversion.completed_at = conversion.completed_at or _now()
    await db.flush()
    return await grant_conversion_reward(db, conversion)


async def summary_for_inviter(
    db: AsyncSession, *, inviter_user_id: str
) -> dict[str, int]:
    links = (
        await db.execute(
            select(InvitationLink.id).where(
                InvitationLink.inviter_user_id == inviter_user_id
            )
        )
    ).scalars().all()
    if not links:
        return {
            "persons_registered": 0,
            "businesses_registered": 0,
            "points_earned": 0,
            "points_pending": 0,
        }
    rows = (
        await db.execute(
            select(InvitationConversion).where(
                InvitationConversion.link_id.in_(links)
            )
        )
    ).scalars().all()
    persons = sum(
        1
        for c in rows
        if c.kind == KIND_PERSON and c.completed_at is not None
    )
    businesses = sum(
        1
        for c in rows
        if c.kind == KIND_BUSINESS and c.completed_at is not None
    )
    earned = sum(c.reward_points for c in rows if c.status == STATUS_GRANTED)
    pending = sum(
        c.reward_points
        for c in rows
        if c.status in {STATUS_PENDING, STATUS_FAILED} and c.completed_at
    )
    return {
        "persons_registered": persons,
        "businesses_registered": businesses,
        "points_earned": earned,
        "points_pending": pending,
    }


def conversion_to_dict(
    conversion: InvitationConversion,
    *,
    public_code: str | None = None,
    inviter_user_id: str | None = None,
) -> dict:
    status = conversion.status
    if status == STATUS_PENDING:
        ui_status = "pending"
    elif status == STATUS_GRANTED:
        ui_status = "granted"
    else:
        ui_status = "pending"
    return {
        "id": conversion.id,
        "kind": conversion.kind,
        "status": ui_status if status != STATUS_FAILED else "pending",
        "display_name": conversion.display_name,
        "completed_at": conversion.completed_at,
        "granted_at": conversion.granted_at,
        "points": conversion.reward_points,
        "inviter_user_id": inviter_user_id,
        "invitee_user_id": conversion.invitee_user_id,
        "shop_id": conversion.shop_id,
        "town_id": conversion.town_id,
        "public_code": public_code,
    }


async def list_inviter_conversions(
    db: AsyncSession,
    *,
    inviter_user_id: str,
    kind: str | None = None,
    offset: int = 0,
    limit: int = 50,
) -> tuple[list[InvitationConversion], int, dict[str, InvitationLink]]:
    links = (
        await db.execute(
            select(InvitationLink).where(
                InvitationLink.inviter_user_id == inviter_user_id
            )
        )
    ).scalars().all()
    by_id = {link.id: link for link in links}
    if not by_id:
        return [], 0, {}
    filters = [InvitationConversion.link_id.in_(by_id.keys())]
    if kind in VALID_KINDS:
        filters.append(InvitationConversion.kind == kind)
    total = int(
        (
            await db.execute(
                select(func.count()).select_from(InvitationConversion).where(*filters)
            )
        ).scalar_one()
    )
    rows = (
        await db.execute(
            select(InvitationConversion)
            .where(*filters)
            .order_by(InvitationConversion.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
    ).scalars().all()
    return rows, total, by_id


async def count_share_events(
    db: AsyncSession, *, town_id: str | None = None, link_ids: list[str] | None = None
) -> int:
    q = select(func.count()).select_from(InvitationEvent).where(
        InvitationEvent.event_type == EVENT_SHARE
    )
    if link_ids is not None:
        if not link_ids:
            return 0
        q = q.where(InvitationEvent.link_id.in_(link_ids))
    elif town_id:
        town_links = (
            await db.execute(
                select(InvitationLink.id).where(InvitationLink.town_id == town_id)
            )
        ).scalars().all()
        if not town_links:
            return 0
        q = q.where(InvitationEvent.link_id.in_(town_links))
    return int((await db.execute(q)).scalar_one())
