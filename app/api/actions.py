"""Point actions CRUD (admin)."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.deps import require_admin
from app.models import PointAction, User
from app.schemas import PointActionCreate, PointActionOut, PointActionUpdate

router = APIRouter(prefix="/actions", tags=["actions"])


@router.get("", response_model=list[PointActionOut])
async def list_actions(
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    if not user.town_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Admin has no town")
    rows = (
        await db.execute(
            select(PointAction)
            .where(PointAction.town_id == user.town_id)
            .order_by(PointAction.created_at.desc())
        )
    ).scalars().all()
    return [PointActionOut.model_validate(a) for a in rows]


@router.post("", response_model=PointActionOut, status_code=status.HTTP_201_CREATED)
async def create_action(
    payload: PointActionCreate,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    if not user.town_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Admin has no town")
    action = PointAction(town_id=user.town_id, **payload.model_dump())
    db.add(action)
    await db.commit()
    await db.refresh(action)
    return PointActionOut.model_validate(action)


@router.patch("/{action_id}", response_model=PointActionOut)
async def update_action(
    action_id: str,
    payload: PointActionUpdate,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    action = await db.get(PointAction, action_id)
    if not action or action.town_id != user.town_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Action not found")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(action, field, value)
    await db.commit()
    await db.refresh(action)
    return PointActionOut.model_validate(action)


@router.post("/{action_id}/activate", response_model=PointActionOut)
async def activate_action(
    action_id: str,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    action = await db.get(PointAction, action_id)
    if not action or action.town_id != user.town_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Action not found")
    action.active = True
    await db.commit()
    await db.refresh(action)
    return PointActionOut.model_validate(action)


@router.post("/{action_id}/deactivate", response_model=PointActionOut)
async def deactivate_action(
    action_id: str,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    action = await db.get(PointAction, action_id)
    if not action or action.town_id != user.town_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Action not found")
    action.active = False
    await db.commit()
    await db.refresh(action)
    return PointActionOut.model_validate(action)
