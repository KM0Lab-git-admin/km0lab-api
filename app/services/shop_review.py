"""A shop that asks to join waits for a person to approve it.

Until now a shop that registered itself became active the moment its owner
logged in, with nobody looking: anyone could open a shop in any
municipality, and an active shop with a QR is a source of points.

States of a shop (``shops.status``, free text: no migration):

- ``review``: asked to join, waiting for validation. Not public.
- ``rejected``: not approved. Not public; deleted after 30 days.
- ``pending``: registered by the administrator, waiting for its owner's
  first login (unchanged).
- ``active`` / ``inactive``: as before.

Nothing of a shop in ``review`` or ``rejected`` exists in public: not in the
list, not by its id, and it has no QR until it is approved.

What the machine checks (the request is refused, or the administrator is
warned) and what only a person can know (that the shop exists and that
whoever asks runs it) is in ``review_checks``. The administrator of the
municipality approves or rejects; rejecting needs a reason, which goes in
the email to the shop and is not stored.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from sqlalchemy import case, delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    InvitationConversion,
    InvitationLink,
    Shop,
    ShopMedia,
    TownPostalCode,
    User,
)
from app.roles import ROLE_ADMIN, ROLE_MERCHANT, ROLE_RESIDENT
from app.schemas.auth import ShopRequestOut, UserOut
from app.services.invitations import convert_business_activation
from app.services.shop_qr import ensure_shop_qr
from app.services.tax_id import is_valid_tax_id, normalize_tax_id
from app.services.towns import assign_user_to_town

SHOP_REVIEW = "review"
SHOP_REJECTED = "rejected"
# A request in any of these already stands for that shop.
STANDING = (SHOP_REVIEW, "pending", "active")
# Rejected requests are deleted after this many days (what the shop is told).
REJECTED_RETENTION_DAYS = 30


class ReviewRefused(Exception):
    """The step cannot be taken; ``code`` says why."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass
class ReviewChecks:
    """What the administrator sees next to a request."""

    tax_id_valid: bool
    postal_code_in_town: bool
    email_verified: bool
    # Other shops of the municipality with the same tax id.
    same_tax_id: list[str] = field(default_factory=list)
    # Other shops of the municipality whose name looks the same: a warning.
    similar_names: list[str] = field(default_factory=list)
    # Who invited the shop, and what they earn if it is approved.
    invited_by: str | None = None
    invite_points: int = 0


def _name_key(name: str) -> str:
    plain = unicodedata.normalize("NFD", name.casefold())
    plain = "".join(ch for ch in plain if unicodedata.category(ch) != "Mn")
    return re.sub(r"[^a-z0-9]+", "", plain)


def names_look_alike(a: str, b: str) -> bool:
    """"Forn Pere" and "FORN  PERE S.L." are the same shop to a person."""
    ka, kb = _name_key(a), _name_key(b)
    if min(len(ka), len(kb)) < 4:
        return ka == kb
    return ka in kb or kb in ka


async def shops_with_tax_id(
    db: AsyncSession, *, town_id: str, tax_id: str, is_fake: bool, exclude_id: str | None = None
) -> list[Shop]:
    wanted = normalize_tax_id(tax_id)
    if not wanted:
        return []
    rows = (
        await db.execute(
            select(Shop).where(
                Shop.town_id == town_id,
                Shop.is_fake.is_(is_fake),
                Shop.status.in_(STANDING),
                Shop.tax_id.is_not(None),
            )
        )
    ).scalars().all()
    return [
        s
        for s in rows
        if s.id != exclude_id and normalize_tax_id(s.tax_id) == wanted
    ]


async def review_checks(db: AsyncSession, shop: Shop) -> ReviewChecks:
    """Everything the machine can say about a request."""
    others = (
        await db.execute(
            select(Shop).where(
                Shop.town_id == shop.town_id,
                Shop.is_fake.is_(shop.is_fake),
                Shop.status.in_(STANDING),
                Shop.id != shop.id,
            )
        )
    ).scalars().all()
    wanted = normalize_tax_id(shop.tax_id)
    postal_town = await db.scalar(
        select(TownPostalCode.town_id).where(
            TownPostalCode.postal_code == (shop.postal_code or "")
        )
    )
    owner = await db.scalar(select(User.id).where(User.email == shop.contact_email))
    conversion = (
        await db.execute(
            select(InvitationConversion).where(InvitationConversion.shop_id == shop.id)
        )
    ).scalars().first()
    invited_by = None
    if conversion is not None:
        inviter = await db.scalar(
            select(User)
            .join(InvitationLink, InvitationLink.inviter_user_id == User.id)
            .where(InvitationLink.id == conversion.link_id)
        )
        if inviter is not None:
            invited_by = inviter.name or inviter.slug
    return ReviewChecks(
        tax_id_valid=is_valid_tax_id(shop.tax_id),
        postal_code_in_town=postal_town == shop.town_id,
        email_verified=owner is not None,
        same_tax_id=[
            s.name for s in others if wanted and normalize_tax_id(s.tax_id) == wanted
        ],
        similar_names=[s.name for s in others if names_look_alike(s.name, shop.name)],
        invited_by=invited_by,
        invite_points=conversion.reward_points if conversion is not None else 0,
    )


async def approve_shop(db: AsyncSession, shop: Shop) -> User | None:
    """Approve a request: the shop goes live, gets its QR and its owner.

    Returns the owner when the account that asked could be given the shop
    (it always can, unless it became an administrator or took another shop
    in the meantime: then the shop waits for whoever logs in with its
    contact email, like one registered by the administrator).
    """
    if shop.status not in (SHOP_REVIEW, SHOP_REJECTED):
        raise ReviewRefused("shop_not_in_review", "This shop is not waiting for validation.")
    shop.status = "active"
    await ensure_shop_qr(db, shop)

    owner = (
        await db.execute(select(User).where(User.email == shop.contact_email))
    ).scalars().first()
    if (
        owner is None
        or owner.has_role(ROLE_ADMIN)
        or owner.shop_id
        or owner.is_fake != shop.is_fake
    ):
        await db.flush()
        return None
    owner.set_roles(list({*owner.roles, ROLE_RESIDENT, ROLE_MERCHANT}))
    owner.shop_id = shop.id
    await assign_user_to_town(db, owner, shop.town_id)
    # Whoever invited the shop is paid now: an approved shop, not a form sent.
    await convert_business_activation(db, user=owner, shop=shop)
    await db.flush()
    return owner


async def reject_shop(db: AsyncSession, shop: Shop) -> None:
    """Reject a request. The reason travels in the email, not here."""
    if shop.status != SHOP_REVIEW:
        raise ReviewRefused("shop_not_in_review", "This shop is not waiting for validation.")
    shop.status = SHOP_REJECTED
    # The 30 days before deletion count from this moment.
    shop.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
    await db.flush()


async def purge_rejected_shops(
    db: AsyncSession, *, older_than_days: int = REJECTED_RETENTION_DAYS, apply: bool
) -> list[tuple[str, datetime]]:
    """Delete rejected requests older than ``older_than_days``.

    The shop was told its data would be deleted within 30 days. What goes:
    the request itself, its pictures and the note of who invited it (never
    paid). The account of whoever asked is not touched: it is a resident's.
    Returns (name, rejected at) of each request, deleted or not.
    """
    cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(
        days=older_than_days
    )
    rows = (
        await db.execute(
            select(Shop)
            .where(Shop.status == SHOP_REJECTED, Shop.updated_at < cutoff)
            .order_by(Shop.updated_at)
        )
    ).scalars().all()
    out = [(shop.name, shop.updated_at) for shop in rows]
    if apply and rows:
        ids = [shop.id for shop in rows]
        await db.execute(
            delete(InvitationConversion).where(InvitationConversion.shop_id.in_(ids))
        )
        await db.execute(delete(ShopMedia).where(ShopMedia.shop_id.in_(ids)))
        await db.execute(delete(Shop).where(Shop.id.in_(ids)))
        await db.flush()
    return out


async def shop_request_of(db: AsyncSession, user: User) -> Shop | None:
    """The request this person is waiting on (or was refused), if any."""
    if user.shop_id or user.has_role(ROLE_ADMIN):
        return None
    return (
        await db.execute(
            select(Shop)
            .where(
                Shop.contact_email == user.email,
                Shop.status.in_((SHOP_REVIEW, SHOP_REJECTED)),
            )
            # The one still waiting first (asked again after a rejection),
            # then the newest.
            .order_by(
                case((Shop.status == SHOP_REVIEW, 0), else_=1),
                Shop.created_at.desc(),
            )
        )
    ).scalars().first()


async def user_out(db: AsyncSession, user: User) -> UserOut:
    """The user as the frontends get it, with their request if any."""
    out = UserOut.model_validate(user)
    request = await shop_request_of(db, user)
    if request is not None:
        out.shop_request = ShopRequestOut(
            shop_id=request.id, name=request.name, status=request.status
        )
    return out


async def requests_waiting(db: AsyncSession, *, town_id: str, is_fake: bool) -> int:
    return int(
        await db.scalar(
            select(func.count())
            .select_from(Shop)
            .where(
                Shop.town_id == town_id,
                Shop.is_fake.is_(is_fake),
                Shop.status == SHOP_REVIEW,
            )
        )
        or 0
    )
