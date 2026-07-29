"""Town config endpoints (admin of that town)."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db import get_db
from app.deps import assert_town_scope, require_admin
from app.models import Town, User
from app.schemas import TownOut, TownUpdate
from app.utils.slug import slugify

router = APIRouter(prefix="/towns", tags=["towns"])


async def _load_town(db: AsyncSession, town_id: str) -> Town | None:
    return (
        await db.execute(
            select(Town)
            .options(selectinload(Town.postal_codes))
            .where(Town.id == town_id)
        )
    ).scalars().first()


@router.get("/me", response_model=TownOut)
async def get_my_town(
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    if not user.town_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="No town linked")
    town = await _load_town(db, user.town_id)
    if not town:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Town not found")
    return TownOut.model_validate(town)


@router.get("/{town_id}", response_model=TownOut)
async def get_town(
    town_id: str,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    assert_town_scope(user, town_id)
    town = await _load_town(db, town_id)
    if not town:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Town not found")
    return TownOut.model_validate(town)


@router.patch("/{town_id}", response_model=TownOut)
async def update_town(
    town_id: str,
    payload: TownUpdate,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    assert_town_scope(user, town_id)
    town = await _load_town(db, town_id)
    if not town:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Town not found")
    data = payload.model_dump(exclude_unset=True)
    if "slug" in data:
        wanted = slugify(data.pop("slug") or "")
        taken = (
            await db.execute(
                select(Town.id).where(Town.slug == wanted, Town.id != town.id)
            )
        ).scalar_one_or_none()
        if taken:
            raise HTTPException(
                status.HTTP_409_CONFLICT, detail="Slug already in use"
            )
        town.slug = wanted
    for field, value in data.items():
        setattr(town, field, value)
    await db.commit()
    town = await _load_town(db, town_id)
    return TownOut.model_validate(town)
