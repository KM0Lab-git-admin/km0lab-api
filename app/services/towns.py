"""Postal-code ↔ town helpers."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.demo import (
    DEMO_POSTAL_CODE,
    DEMO_TOWN_NAME,
    DEMO_TOWN_SLUG,
    MALGRAT_CONTENT_TOWN,
    MALGRAT_CP,
    is_demo_postal_code,
)
from app.models import Town, TownPostalCode, User


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


async def get_town_by_slug(db: AsyncSession, slug: str) -> Town | None:
    return (
        await db.execute(select(Town).where(Town.slug == slug))
    ).scalars().first()


async def ensure_demo_town(db: AsyncSession) -> Town:
    """Idempotent: Demo KM0 town + CP 00000 for product demos."""
    existing_cp = await get_postal_code(db, DEMO_POSTAL_CODE)
    if existing_cp is not None:
        town = await db.get(Town, existing_cp.town_id)
        if town is not None:
            return town

    town = (
        await db.execute(select(Town).where(Town.slug == DEMO_TOWN_SLUG))
    ).scalars().first()
    if town is None:
        town = Town(
            name=DEMO_TOWN_NAME,
            slug=DEMO_TOWN_SLUG,
            entity_name="KM0 LAB Demo",
            entity_type="private",
            contact_email="demo@km0lab.com",
            manager_name="Demo KM0",
            default_lang="ca",
        )
        db.add(town)
        await db.flush()

    db.add(
        TownPostalCode(
            postal_code=DEMO_POSTAL_CODE,
            town_id=town.id,
            is_primary=True,
        )
    )
    await db.flush()
    return town


def municipal_content_poblacion(
    postal_code: str | None, town_name: str | None
) -> str:
    """Population name for agenda/news APIs (Demo falls back to Malgrat)."""
    if is_demo_postal_code(postal_code):
        return MALGRAT_CONTENT_TOWN
    return (town_name or MALGRAT_CONTENT_TOWN).strip() or MALGRAT_CONTENT_TOWN


async def resolve_malgrat_town(db: AsyncSession) -> Town | None:
    cp = await get_postal_code(db, MALGRAT_CP)
    if cp is not None:
        return await db.get(Town, cp.town_id)
    return (
        await db.execute(select(Town).where(Town.name == MALGRAT_CONTENT_TOWN))
    ).scalars().first()
