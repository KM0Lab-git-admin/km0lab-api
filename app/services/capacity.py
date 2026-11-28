"""How many accounts a municipality admits, and the terms a person accepted.

**Capacity.** A pilot is for a limited group: a municipality may set a
maximum of accounts (``towns.max_residents``; null = no limit). Everyone
who registers counts, invited or not, in order of arrival. Once it is
full, a new registration there is answered with ``pilot_full``.

What never counts and is never limited: the demonstration and the QA
territory (make-believe accounts), and whoever already has their account in
the municipality, who can always log in. A shop owner invited by the
administrator gets in even when the municipality is full: the shop is part
of the pilot.

**Terms.** The app does not let anyone ask for a code without ticking the
box, and sends the version they accepted. The account keeps that version
and the moment, as proof. Nothing else is stored: no IP, no device.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Town, TownPostalCode, User

PILOT_FULL = "pilot_full"
PILOT_FULL_MESSAGE = "El pilot d'aquesta població està complet."

# The version of the pilot terms and the privacy policy in force. Raising it
# makes every account accept once more.
CURRENT_TERMS_VERSION = "2"


async def residents_count(db: AsyncSession, town_id: str) -> int:
    """Real accounts whose postal code belongs to the municipality."""
    codes = select(TownPostalCode.postal_code).where(
        TownPostalCode.town_id == town_id
    )
    return int(
        await db.scalar(
            select(func.count())
            .select_from(User)
            .where(User.postal_code.in_(codes), User.is_fake.is_(False))
        )
        or 0
    )


async def town_is_full(
    db: AsyncSession, town_id: str | None, *, lock: bool = False
) -> bool:
    """No room for one more account. ``lock`` takes the municipality's row
    first, so two people registering at once cannot both take the last
    place."""
    if not town_id:
        return False
    query = select(Town.max_residents).where(Town.id == town_id)
    if lock:
        query = query.with_for_update()
    limit = await db.scalar(query)
    if limit is None:
        return False
    return await residents_count(db, town_id) >= limit


def accept_terms(user: User, version: str | None) -> bool:
    """Record that ``user`` accepted ``version``. Only the version in force
    counts, and accepting it again does not move the date."""
    if version != CURRENT_TERMS_VERSION or user.terms_version == version:
        return False
    user.terms_version = version
    user.terms_accepted_at = datetime.now(timezone.utc).replace(tzinfo=None)
    return True
