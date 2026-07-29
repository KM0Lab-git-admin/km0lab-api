"""Postal-code ↔ town helpers."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import TownPostalCode, User


async def get_postal_code(db: AsyncSession, postal_code: str) -> TownPostalCode | None:
    return (
        await db.execute(
            select(TownPostalCode)
            .options(selectinload(TownPostalCode.town))
            .where(TownPostalCode.postal_code == postal_code)
        )
    ).scalars().first()


async def get_primary_postal_code(
    db: AsyncSession, town_id: str
) -> TownPostalCode | None:
    primary = (
        await db.execute(
            select(TownPostalCode)
            .options(selectinload(TownPostalCode.town))
            .where(
                TownPostalCode.town_id == town_id,
                TownPostalCode.is_primary.is_(True),
            )
        )
    ).scalars().first()
    if primary:
        return primary
    return (
        await db.execute(
            select(TownPostalCode)
            .options(selectinload(TownPostalCode.town))
            .where(TownPostalCode.town_id == town_id)
            .order_by(TownPostalCode.postal_code)
        )
    ).scalars().first()


async def assign_user_to_town(
    db: AsyncSession, user: User, town_id: str
) -> None:
    """If the user has no postal_code yet, set the town's primary CP."""
    if user.postal_code:
        return
    postal = await get_primary_postal_code(db, town_id)
    if postal is None:
        return
    user.postal_code = postal.postal_code
    # Keep identity map in sync for town_id property in this request.
    user.postal_ref = postal


async def load_user_with_town(db: AsyncSession, user_id: str) -> User | None:
    return (
        await db.execute(
            select(User)
            .options(
                selectinload(User.postal_ref).selectinload(TownPostalCode.town)
            )
            .where(User.id == user_id)
        )
    ).scalars().first()
