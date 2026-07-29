"""Point actions CRUD (admin).

Partitioned by ``user.is_fake``: demo admin only sees/edits fake actions.
"""

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
            .where(
                PointAction.town_id == user.town_id,
                PointAction.is_fake.is_(user.is_fake),
            )
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
    action = PointAction(
        town_id=user.town_id, is_fake=user.is_fake, **payload.model_dump()
    )
    db.add(action)
    await db.commit()
    await db.refresh(action)
    return PointActionOut.model_validate(action)


async def _get_town_action(
    db: AsyncSession, *, action_id: str, town_id: str, is_fake: bool
) -> PointAction:
    action = await db.get(PointAction, action_id)
    if (
        not action
        or action.town_id != town_id
        or action.is_fake != is_fake
    ):
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Action not found")
    return action


@router.patch("/{action_id}", response_model=PointActionOut)
async def update_action(
    action_id: str,
    payload: PointActionUpdate,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    if not user.town_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Admin has no town")
    action = await _get_town_action(
        db, action_id=action_id, town_id=user.town_id, is_fake=user.is_fake
    )
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
    if not user.town_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Admin has no town")
    action = await _get_town_action(
        db, action_id=action_id, town_id=user.town_id, is_fake=user.is_fake
    )
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
    if not user.town_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Admin has no town")
    action = await _get_town_action(
        db, action_id=action_id, town_id=user.town_id, is_fake=user.is_fake
    )
    action.active = False
    await db.commit()
    await db.refresh(action)
    return PointActionOut.model_validate(action)


@router.delete("/{action_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_action(
    action_id: str,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    if not user.town_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Admin has no town")
    action = await _get_town_action(
        db, action_id=action_id, town_id=user.town_id, is_fake=user.is_fake
    )
    await db.delete(action)
    await db.commit()
