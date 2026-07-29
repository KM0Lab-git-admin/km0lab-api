"""Validate shop category slugs against the catalog."""

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ShopCategory


async def resolve_category_slugs(
    db: AsyncSession,
    slugs: list[str] | None,
    *,
    required_active: bool = True,
) -> list[str]:
    """Normalize and validate category slugs. Raises 400 on unknown/inactive."""
    if not slugs:
        return []

    cleaned: list[str] = []
    seen: set[str] = set()
    for raw in slugs:
        slug = str(raw).strip().lower()
        if not slug or slug in seen:
            continue
        seen.add(slug)
        cleaned.append(slug)

    if not cleaned:
        return []

    stmt = select(ShopCategory).where(ShopCategory.slug.in_(cleaned))
    rows = {c.slug: c for c in (await db.execute(stmt)).scalars().all()}

    unknown = [s for s in cleaned if s not in rows]
    if unknown:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown shop categories: {', '.join(unknown)}",
        )

    if required_active:
        inactive = [s for s in cleaned if not rows[s].active]
        if inactive:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                detail=f"Inactive shop categories: {', '.join(inactive)}",
            )

    return cleaned
