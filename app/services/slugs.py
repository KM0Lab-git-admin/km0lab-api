"""Allocate unique slugs for towns and users."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Town, User
from app.utils.slug import slugify


async def allocate_town_slug(
    db: AsyncSession, name: str, *, exclude_id: str | None = None
) -> str:
    base = slugify(name)
    return await _unique_town(db, base, exclude_id=exclude_id)


async def allocate_user_slug(
    db: AsyncSession,
    *,
    first_name: str | None = None,
    last_name: str | None = None,
    email: str | None = None,
    exclude_id: str | None = None,
) -> str:
    source = " ".join(p for p in (first_name, last_name) if p).strip()
    if not source and email:
        source = email.split("@")[0]
    base = slugify(source or "user")
    return await _unique_user(db, base, exclude_id=exclude_id)


async def _unique_town(
    db: AsyncSession, base: str, *, exclude_id: str | None
) -> str:
    slug = base
    n = 2
    while True:
        stmt = select(Town.id).where(Town.slug == slug)
        if exclude_id:
            stmt = stmt.where(Town.id != exclude_id)
        if (await db.execute(stmt)).scalar_one_or_none() is None:
            return slug
        suffix = f"-{n}"
        slug = f"{base[: 80 - len(suffix)]}{suffix}"
        n += 1


async def _unique_user(
    db: AsyncSession, base: str, *, exclude_id: str | None
) -> str:
    slug = base
    n = 2
    while True:
        stmt = select(User.id).where(User.slug == slug)
        if exclude_id:
            stmt = stmt.where(User.id != exclude_id)
        if (await db.execute(stmt)).scalar_one_or_none() is None:
            return slug
        suffix = f"-{n}"
        slug = f"{base[: 80 - len(suffix)]}{suffix}"
        n += 1
