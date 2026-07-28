"""Town config endpoints (admin of that town)."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.deps import assert_town_scope, require_admin
from app.models import Town, User
from app.schemas import TownOut, TownUpdate

router = APIRouter(prefix="/towns", tags=["towns"])


@router.get("/me", response_model=TownOut)
async def get_my_town(
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    if not user.town_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="No town linked")
    town = await db.get(Town, user.town_id)
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
    town = await db.get(Town, town_id)
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
    town = await db.get(Town, town_id)
    if not town:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Town not found")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(town, field, value)
    await db.commit()
    await db.refresh(town)
    return TownOut.model_validate(town)
