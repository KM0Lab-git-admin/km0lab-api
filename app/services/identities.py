"""The ways a person gets into their account, and where the account came from.

An account is still one email (``users.email``, unique and required). What
this adds is a record of **how** the person gets in: one row of
``user_identities`` per door.

- ``email_code``: the code sent to their email. ``subject`` is the email in
  lower case.
- ``google`` / ``facebook`` / ``apple``: ``subject`` is the stable id that
  provider gives for that person (never the email: it can change or be
  hidden).

The door the account was born with is marked ``is_first``: that is the
origin the administrator sees ("came in by Google"). Linking another door
later never changes it. No token of any provider is stored: they are
verified and thrown away.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import TownPostalCode, User, UserIdentity

PROVIDER_EMAIL = "email_code"
PROVIDER_GOOGLE = "google"
PROVIDER_FACEBOOK = "facebook"
PROVIDER_APPLE = "apple"
# In the order the app shows them.
SOCIAL_PROVIDERS = (PROVIDER_GOOGLE, PROVIDER_FACEBOOK, PROVIDER_APPLE)
ALL_PROVIDERS = (PROVIDER_EMAIL, *SOCIAL_PROVIDERS)

# Apple lets a person hide their email: it gives one of these instead,
# unique and stable for that person and this app. It is not their mailbox.
APPLE_RELAY_DOMAIN = "@privaterelay.appleid.com"


class IdentityTaken(Exception):
    """That door already opens another account. It is never moved."""


def is_hidden_email(email: str | None) -> bool:
    return (email or "").strip().lower().endswith(APPLE_RELAY_DOMAIN)


def _subject(provider: str, subject: str) -> str:
    subject = (subject or "").strip()
    return subject.lower() if provider == PROVIDER_EMAIL else subject


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


async def find_identity(
    db: AsyncSession, provider: str, subject: str
) -> UserIdentity | None:
    return (
        await db.execute(
            select(UserIdentity).where(
                UserIdentity.provider == provider,
                UserIdentity.subject == _subject(provider, subject),
            )
        )
    ).scalars().first()


async def ensure_identity(
    db: AsyncSession,
    user: User,
    *,
    provider: str,
    subject: str,
    email: str | None = None,
) -> UserIdentity:
    """Note that ``user`` has just come in through this door.

    The first door an account ever uses is its origin (``is_first``); that
    covers an account being born now and one created by a script that logs
    in for the first time. Raises ``IdentityTaken`` if the door belongs to
    another account.
    """
    subject = _subject(provider, subject)
    row = await find_identity(db, provider, subject)
    if row is None:
        has_any = await db.scalar(
            select(UserIdentity.id).where(UserIdentity.user_id == user.id).limit(1)
        )
        row = UserIdentity(
            user_id=user.id,
            provider=provider,
            subject=subject,
            email=email,
            is_first=has_any is None,
        )
        try:
            async with db.begin_nested():
                db.add(row)
                await db.flush()
        except IntegrityError:
            # Two logins at once: the other one wrote it first.
            row = await find_identity(db, provider, subject)
            if row is None:
                raise
    if row.user_id != user.id:
        raise IdentityTaken(provider)
    row.last_used_at = _now()
    if email:
        row.email = email
    await db.flush()
    return row


async def identities_of(db: AsyncSession, user_id: str) -> list[UserIdentity]:
    """Every door of an account, the one it was born with first."""
    rows = (
        await db.execute(
            select(UserIdentity)
            .where(UserIdentity.user_id == user_id)
            .order_by(UserIdentity.is_first.desc(), UserIdentity.created_at, UserIdentity.id)
        )
    ).scalars().all()
    return list(rows)


async def origins_of(db: AsyncSession, user_ids: list[str]) -> dict[str, UserIdentity]:
    """The door each of these accounts was born with (one query)."""
    if not user_ids:
        return {}
    rows = (
        await db.execute(
            select(UserIdentity)
            .where(UserIdentity.user_id.in_(user_ids), UserIdentity.is_first.is_(True))
            .order_by(UserIdentity.created_at, UserIdentity.id)
        )
    ).scalars().all()
    out: dict[str, UserIdentity] = {}
    for row in rows:
        out.setdefault(row.user_id, row)
    return out


async def signups_by_provider(
    db: AsyncSession, *, town_id: str | None, is_fake: bool
) -> dict[str, int]:
    """How many residents were born through each door.

    ``town_id`` limits it to one municipality; ``None`` counts them all
    (only the report script does that). An account with no identity yet
    (created by a script, never logged in) is not counted.
    """
    stmt = (
        select(UserIdentity.provider, func.count(func.distinct(UserIdentity.user_id)))
        .join(User, User.id == UserIdentity.user_id)
        .where(
            UserIdentity.is_first.is_(True),
            User.is_resident.is_(True),
            User.is_fake.is_(is_fake),
        )
        .group_by(UserIdentity.provider)
    )
    if town_id is not None:
        stmt = stmt.join(
            TownPostalCode, User.postal_code == TownPostalCode.postal_code
        ).where(TownPostalCode.town_id == town_id)
    counts = {provider: 0 for provider in ALL_PROVIDERS}
    for provider, total in (await db.execute(stmt)).all():
        counts[provider] = int(total)
    return counts
